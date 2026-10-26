"""Command-line interface for ofdkit."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import __version__
from .document import OFDDocument
from .errors import OFDError
from .invoice import Invoice
from .markdown import document_markdown

EXIT_OK = 0
EXIT_NO_INVOICE = 1
EXIT_ERROR = 2

CSV_COLUMNS = [
    "file",
    "invoice_number",
    "invoice_code",
    "issue_date",
    "buyer_name",
    "buyer_tax_id",
    "seller_name",
    "seller_tax_id",
    "amount_without_tax",
    "tax_amount",
    "total_amount",
    "items",
    "warnings",
    "error",
]


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _replace_unencodable_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    commands = {"info": _info, "text": _text, "invoice": _invoice, "batch": _batch}
    try:
        return commands[args.command](args)
    except (OFDError, OSError) as exc:
        print(f"ofdkit: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _info(args: argparse.Namespace) -> int:
    with OFDDocument(args.file) as document:
        invoice = document.invoice()
        data = {
            "file": args.file,
            "pages": [
                {"number": page.index + 1, "id": page.id, "width_mm": page.width, "height_mm": page.height}
                for page in document.pages
            ],
            "info": document.info.to_dict(),
            "is_invoice": invoice is not None,
            "warnings": list(document.warnings),
        }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK

    info = data["info"]
    sizes = sorted({(page["width_mm"], page["height_mm"]) for page in data["pages"]})
    size_text = ", ".join(f"{_number(w)} x {_number(h)} mm" for w, h in sizes)
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
    files = _find_files(args.paths, args.recursive)
    if not files:
        print("ofdkit: error: no .ofd files found", file=sys.stderr)
        return EXIT_ERROR

    rows = [_batch_row(path) for path in files]
    numbers = Counter(row["invoice_number"] for row in rows if row["invoice_number"])
    for row in rows:
        if numbers.get(row["invoice_number"], 0) > 1:
            row["warnings"] = "; ".join(filter(None, [row["warnings"], "duplicate invoice number"]))

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8-sig") as stream:
            _write_csv(stream, rows)
    else:
        _write_csv(sys.stdout, rows)

    invoices = [row for row in rows if not row["error"]]
    total = sum((_decimal(row["total_amount"]) for row in invoices), Decimal(0))
    print(
        f"ofdkit: {len(files)} files, {len(invoices)} invoices, {len(rows) - len(invoices)} without invoice data; "
        f"total_amount sum {total}",
        file=sys.stderr,
    )
    return EXIT_OK


def _find_files(paths: Sequence[str], recursive: bool) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            candidates = path.rglob("*") if recursive else path.glob("*")
            found.extend(sorted(p for p in candidates if p.is_file() and p.suffix.lower() == ".ofd"))
        elif path.exists():
            found.append(path)
        else:
            print(f"ofdkit: warning: {raw} does not exist", file=sys.stderr)
    return found


def _batch_row(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(CSV_COLUMNS, "")
    row["file"] = str(path)
    try:
        with OFDDocument(path) as document:
            invoice = document.invoice()
    except (OFDError, OSError) as exc:
        row["error"] = str(exc)
        return row
    if invoice is None:
        row["error"] = "no invoice data"
        return row
    row.update(_invoice_columns(invoice))
    return row


def _invoice_columns(invoice: Invoice) -> dict[str, Any]:
    return {
        "invoice_number": invoice.invoice_number or "",
        "invoice_code": invoice.invoice_code or "",
        "issue_date": invoice.issue_date or "",
        "buyer_name": invoice.buyer.name or "",
        "buyer_tax_id": invoice.buyer.tax_id or "",
        "seller_name": invoice.seller.name or "",
        "seller_tax_id": invoice.seller.tax_id or "",
        "amount_without_tax": invoice.amount_without_tax or "",
        "tax_amount": invoice.tax_amount or "",
        "total_amount": invoice.total_amount or "",
        "items": len(invoice.items),
        "warnings": "; ".join(invoice.warnings),
    }


def _write_csv(stream: Any, rows: list[dict[str, Any]]) -> None:
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal(0)


def _number(value: float) -> str:
    return f"{value:g}"


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
