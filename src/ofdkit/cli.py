"""Command-line interface for ofdkit."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .batch import COLUMNS, find_ofd_files, invoice_rows, summary
from .document import OFDDocument
from .errors import OFDError
from .markdown import document_markdown

EXIT_OK = 0
EXIT_NO_INVOICE = 1
EXIT_ERROR = 2

# Kept for backward compatibility with code that imported it from here.
CSV_COLUMNS = COLUMNS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofdkit",
        description="Read OFD documents (GB/T 33190) and Chinese e-invoices.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    info = commands.add_parser("info", help="show pages, metadata and whether the file is an invoice")
    info.add_argument("file", help="OFD file")
    info.add_argument("--json", action="store_true", help="print JSON")

    text = commands.add_parser("text", help="print the text in reading order")
    text.add_argument("file", help="OFD file")
    text.add_argument("-o", "--output", help="write to this file (UTF-8) instead of the screen")
    text.add_argument("--markdown", action="store_true", help="print Markdown, with an invoice table for e-invoices")

    invoice = commands.add_parser("invoice", help="print invoice fields as JSON")
    invoice.add_argument("file", help="OFD file")
    invoice.add_argument("--raw", action="store_true", help="also print every value found, by element path")

    batch = commands.add_parser("batch", help="list the invoices in files and folders as CSV")
    batch.add_argument("paths", nargs="+", metavar="PATH", help="OFD files or folders")
    batch.add_argument("-o", "--output", help="CSV file to write (UTF-8 with BOM, so Excel shows Chinese correctly)")
    batch.add_argument("-r", "--recursive", action="store_true", help="also look in subfolders")

    describe = commands.add_parser(
        "describe", help="print the file's structure as JSON with all text masked, for bug reports"
    )
    describe.add_argument("file", help="OFD file")
    describe.add_argument("-o", "--output", help="write to this file (UTF-8) instead of the screen")

    mcp = commands.add_parser("mcp", help='run an MCP server over stdio for AI tools (needs "ofdkit[mcp]")')
    mcp.add_argument("--root", help="only allow reading files inside this folder")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _replace_unencodable_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    commands = {"info": _info, "text": _text, "invoice": _invoice, "batch": _batch, "describe": _describe, "mcp": _mcp}
    try:
        return commands[args.command](args)
    except (OFDError, OSError) as exc:
        print(f"ofdkit: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _info(args: argparse.Namespace) -> int:
    with OFDDocument(args.file) as document:
        data = file_info(document, args.file)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK

    info = data["info"]
    sizes = sorted({(page["width_mm"], page["height_mm"]) for page in data["pages"]})
    size_text = ", ".join(f"{w:g} x {h:g} mm" for w, h in sizes)
    lines = [("File", args.file), ("Pages", f"{len(data['pages'])} ({size_text})" if sizes else "0")]
    for label, key in (("Title", "title"), ("Author", "author"), ("Created", "creation_date"), ("Modified", "mod_date")):
        if info[key]:
            lines.append((label, info[key]))
    if info["creator"]:
        creator = info["creator"] + (f" {info['creator_version']}" if info["creator_version"] else "")
        lines.append(("Creator", creator))
    lines.append(("Invoice", "yes" if data["is_invoice"] else "no"))
    lines.extend(("Warning", warning) for warning in data["warnings"])
    width = max(len(label) for label, _ in lines) + 1
    for label, value in lines:
        print(f"{label + ':':<{width}} {value}")
    return EXIT_OK


def file_info(document: OFDDocument, name: str) -> dict[str, Any]:
    """Pages, metadata and whether the document is an invoice, as plain data."""
    invoice = document.invoice()
    return {
        "file": name,
        "pages": [
            {"number": page.index + 1, "id": page.id, "width_mm": page.width, "height_mm": page.height}
            for page in document.pages
        ],
        "info": document.info.to_dict(),
        "is_invoice": invoice is not None,
        "warnings": list(document.warnings),
    }


def _text(args: argparse.Namespace) -> int:
    with OFDDocument(args.file) as document:
        text = document_markdown(document).rstrip("\n") if args.markdown else document.text()
        warnings = list(document.warnings)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    for warning in warnings:
        print(f"ofdkit: warning: {warning}", file=sys.stderr)
    return EXIT_OK


def _invoice(args: argparse.Namespace) -> int:
    with OFDDocument(args.file) as document:
        invoice = document.invoice()
    if invoice is None:
        print(f"ofdkit: no invoice data found in {args.file}", file=sys.stderr)
        return EXIT_NO_INVOICE
    print(json.dumps(invoice.to_dict(include_raw=args.raw), ensure_ascii=False, indent=2))
    return EXIT_OK


def _batch(args: argparse.Namespace) -> int:
    files, missing = find_ofd_files(args.paths, args.recursive)
    for path in missing:
        print(f"ofdkit: warning: {path} does not exist", file=sys.stderr)
    if not files:
        print("ofdkit: error: no .ofd files found", file=sys.stderr)
        return EXIT_ERROR

    rows = invoice_rows(files)
    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8-sig") as stream:
            _write_csv(stream, rows)
    else:
        _write_csv(sys.stdout, rows)

    totals = summary(rows)
    print(
        f"ofdkit: {totals['files']} files, {totals['invoices']} invoices, "
        f"{totals['files'] - totals['invoices']} without invoice data; "
        f"total_amount sum {totals['total_amount_sum']}",
        file=sys.stderr,
    )
    return EXIT_OK


def _describe(args: argparse.Namespace) -> int:
    from .describe import describe

    text = json.dumps(describe(args.file), ensure_ascii=False, indent=1)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"ofdkit: wrote {args.output}. Text is masked; please check the file before sharing it.", file=sys.stderr)
    else:
        print(text)
    return EXIT_OK


def _mcp(args: argparse.Namespace) -> int:
    try:
        from .mcp_server import create_server
    except ImportError as exc:
        print(f'ofdkit: error: MCP support needs the "mcp" extra: pip install "ofdkit[mcp]" ({exc})', file=sys.stderr)
        return EXIT_ERROR
    create_server(root=args.root).run("stdio")
    return EXIT_OK


def _write_csv(stream: Any, rows: list[dict[str, Any]]) -> None:
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)


def _replace_unencodable_output() -> None:
    """Never crash on a character the console cannot show (old Windows code pages)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    sys.exit(main())
