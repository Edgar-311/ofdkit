"""Command-line interface for ofdkit."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .batch import (
    COLUMNS,
    NO_INVOICE,
    InvoiceFile,
    buyer_mismatch,
    check_buyer,
    find_ofd_files,
    invoice_row,
    problems,
    read_invoice_files,
    summary,
)
from .document import OFDDocument
from .errors import OFDError
from .markdown import document_markdown
from .rename import DEFAULT_PATTERN, FIELDS
from .report import display_width, invoice_report, pad, summary_text, table_report

EXIT_OK = 0
EXIT_NO_INVOICE = 1
EXIT_ERROR = 2

# Kept for backward compatibility with code that imported it from here.
CSV_COLUMNS = COLUMNS

COMMANDS = ("show", "info", "text", "invoice", "batch", "rename", "describe", "mcp")

EXAMPLES = """\
例子 / examples:
  ofdkit 发票.ofd                           看一张发票，或者一个文件的文字
  ofdkit 发票文件夹                         列出文件夹（或 .zip 压缩包）里的发票和合计
  ofdkit batch 发票文件夹 -o 发票汇总.xlsx   导出到 Excel
  ofdkit 发票文件夹 --buyer 公司名或税号      检查发票抬头对不对
  ofdkit rename 发票文件夹                  按发票内容给文件改名（先预览）
  ofdkit text 文件.ofd                      提取文字
  ofdkit invoice 发票.ofd                   发票字段（JSON，给程序用）
"""

SCAN_HINT = "没有找到文字。如果文件里明明有内容，它可能是扫描件（文字是图片），ofdkit 读不出图片里的字。"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ofdkit",
        description="读取 OFD 文件（GB/T 33190）和电子发票。Read OFD documents and Chinese e-invoices.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="命令")

    show = commands.add_parser(
        "show", help="看文件：一张发票显示发票内容，文件夹或压缩包显示发票列表和合计（直接写 ofdkit 路径 也一样）"
    )
    show.add_argument("paths", nargs="+", metavar="路径", help="OFD 文件、文件夹或 .zip 压缩包")
    show.add_argument("-r", "--recursive", action="store_true", help="也看子文件夹")
    _add_buyer_option(show)

    info = commands.add_parser("info", help="页数、作者等信息，以及是不是发票")
    info.add_argument("file", metavar="文件", help="OFD 文件")
    info.add_argument("--json", action="store_true", help="输出 JSON")

    text = commands.add_parser("text", help="按阅读顺序提取文字")
    text.add_argument("file", metavar="文件", help="OFD 文件")
    text.add_argument("-o", "--output", metavar="输出文件", help="保存到这个文件（UTF-8），不显示在屏幕上")
    text.add_argument("--markdown", action="store_true", help="输出 Markdown；电子发票会先列出发票字段表格")

    invoice = commands.add_parser("invoice", help="发票字段，输出 JSON（给程序和 AI 用）")
    invoice.add_argument("file", metavar="文件", help="OFD 文件")
    invoice.add_argument("--raw", action="store_true", help="同时输出找到的所有原始值")

    batch = commands.add_parser("batch", help="把很多发票汇总成 Excel 或 CSV")
    batch.add_argument("paths", nargs="+", metavar="路径", help="OFD 文件、文件夹或 .zip 压缩包")
    batch.add_argument(
        "-o",
        "--output",
        metavar="输出文件",
        help="保存到这个文件：.xlsx 是 Excel 表格（推荐），其他是 CSV（UTF-8，带 BOM）。不写就把 CSV 显示在屏幕上",
    )
    batch.add_argument("-r", "--recursive", action="store_true", help="也看子文件夹")
    _add_buyer_option(batch)

    rename = commands.add_parser("rename", help="按发票内容给文件改名：先预览，加 --apply 才真的改")
    rename.add_argument("paths", nargs="*", metavar="路径", help="OFD 文件或文件夹")
    rename.add_argument("-r", "--recursive", action="store_true", help="也改子文件夹里的文件")
    rename.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        metavar="格式",
        help=f"新名字的格式，默认 {DEFAULT_PATTERN}。可以用的字段：{'、'.join(FIELDS)}",
    )
    rename.add_argument("--apply", action="store_true", help="真的改名（不加就只预览）")
    rename.add_argument("--only-ofd", action="store_true", help="只改 .ofd 文件；不加的话，同名的 PDF、XML 等也一起改")
    rename.add_argument("--undo", metavar="改名记录", help="按改名记录把文件名改回去")

    describe = commands.add_parser("describe", help="导出文件结构（文字、文件名和号码打码），用于报告问题")
    describe.add_argument("file", metavar="文件", help="OFD 文件")
    describe.add_argument("-o", "--output", metavar="输出文件", help="保存到这个文件（UTF-8），不显示在屏幕上")

    mcp = commands.add_parser("mcp", help='启动给 AI 工具用的 MCP 服务器（需要安装 "ofdkit[mcp]"）')
    mcp.add_argument("--root", metavar="文件夹", help="只允许读取这个文件夹里的文件")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _replace_unencodable_output()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if _looks_like_a_path(arguments):
        arguments.insert(0, "show")
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    commands = {
        "show": _show,
        "info": _info,
        "text": _text,
        "invoice": _invoice,
        "batch": _batch,
        "rename": _rename,
        "describe": _describe,
        "mcp": _mcp,
    }
    try:
        return commands[args.command](args)
    except BrokenPipeError:  # output piped into a program that stopped reading, such as head
        _silence_stdout()
        return EXIT_OK
    except FileNotFoundError as exc:
        _say(f"错误：找不到 {exc.filename or exc}")
    except PermissionError as exc:
        _say(f"错误：没有权限读写 {exc.filename or exc}。如果这个文件正在 Excel 等软件里打开，请先关掉再试。")
    except OFDError as exc:
        _say(f"错误：读不出这个文件：{exc}")
    except OSError as exc:
        _say(f"错误：{exc}")
    return EXIT_ERROR


def _looks_like_a_path(arguments: list[str]) -> bool:
    """``ofdkit 发票.ofd`` means ``ofdkit show 发票.ofd``."""
    if not arguments or arguments[0] in COMMANDS or arguments[0].startswith("-"):
        return False
    first = Path(arguments[0])
    return first.exists() or first.suffix.lower() in (".ofd", ".zip")


def _show(args: argparse.Namespace) -> int:
    paths = [Path(path) for path in args.paths]
    if len(paths) == 1 and paths[0].is_file() and paths[0].suffix.lower() != ".zip":
        with OFDDocument(paths[0]) as document:
            invoice = document.invoice()
            text = None if invoice else document.text()
        if invoice is not None:
            result = InvoiceFile(str(paths[0]), invoice=invoice, buyer_mismatch=buyer_mismatch(invoice, args.buyer))
            print(invoice_report(invoice, problems(result)))
        elif text and text.strip():
            print(text)
        else:
            _say(SCAN_HINT)
        return EXIT_OK

    files, missing = find_ofd_files(args.paths, args.recursive)
    for path in missing:
        _say(f"找不到 {path}")
    if not files:
        if not missing:
            _say("没有找到 .ofd 文件。" + ("" if args.recursive else "要连子文件夹一起找，请加 -r。"))
        return EXIT_ERROR
    results = read_invoice_files(files)
    check_buyer(results, args.buyer)
    print(table_report(results))
    print()
    print(summary_text(summary(results)))
    if any(result.invoice for result in results):
        quoted = " ".join(_quote(path) for path in args.paths)
        flags = (" -r" if args.recursive else "") + "".join(f" --buyer {_quote(value)}" for value in args.buyer)
        print(f"\n导出到 Excel：ofdkit batch {quoted}{flags} -o 发票汇总.xlsx")
    return EXIT_OK


def _info(args: argparse.Namespace) -> int:
    with OFDDocument(args.file) as document:
        data = file_info(document, args.file)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK

    info = data["info"]
    sizes = sorted({(page["width_mm"], page["height_mm"]) for page in data["pages"]})
    size_text = "，".join(f"{w:g} x {h:g} mm" for w, h in sizes)
    lines = [("文件", args.file), ("页数", f"{len(data['pages'])}（{size_text}）" if sizes else "0")]
    for label, key in (("标题", "title"), ("作者", "author"), ("创建时间", "creation_date"), ("修改时间", "mod_date")):
        if info[key]:
            lines.append((label, info[key]))
    if info["creator"]:
        creator = info["creator"] + (f" {info['creator_version']}" if info["creator_version"] else "")
        lines.append(("生成软件", creator))
    lines.append(("是否发票", "是" if data["is_invoice"] else "否"))
    lines.extend(("警告", warning) for warning in data["warnings"])
    width = max(display_width(label) for label, _ in lines) + 2
    for label, value in lines:
        print(pad(label, width) + str(value))
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
        empty = not document.text().strip() if args.markdown else not text.strip()
        warnings = list(document.warnings)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    for warning in warnings:
        _say(f"警告：{warning}")
    if empty:
        _say(SCAN_HINT)
    return EXIT_OK


def _invoice(args: argparse.Namespace) -> int:
    with OFDDocument(args.file) as document:
        invoice = document.invoice()
    if invoice is None:
        _say(f"这个文件里没有发票数据（no invoice data）：{args.file}。要看它的文字，请用 ofdkit text")
        return EXIT_NO_INVOICE
    print(json.dumps(invoice.to_dict(include_raw=args.raw), ensure_ascii=False, indent=2))
    return EXIT_OK


def _batch(args: argparse.Namespace) -> int:
    files, missing = find_ofd_files(args.paths, args.recursive)
    for path in missing:
        _say(f"找不到 {path}")
    if not files:
        _say("错误：没有找到 .ofd 文件" + ("" if args.recursive or missing else "。要连子文件夹一起找，请加 -r"))
        return EXIT_ERROR

    results = read_invoice_files(files)
    check_buyer(results, args.buyer)
    output = Path(args.output) if args.output else None
    if output is not None and output.suffix.lower() == ".xlsx":
        from .xlsx import write_invoices_xlsx

        write_invoices_xlsx(results, output)
    elif output is not None:
        with open(output, "w", newline="", encoding="utf-8-sig") as stream:
            _write_csv(stream, [invoice_row(result) for result in results])
    else:
        _write_csv(sys.stdout, [invoice_row(result) for result in results])

    _say(summary_text(summary(results)))
    unreadable = [result for result in results if result.error and result.error != NO_INVOICE]
    for result in unreadable[:5]:
        _say(f"  {result.file}：{problems(result)[0]}")
    if output is not None:
        _say(f"已保存到 {output}")
    return EXIT_OK


def _rename(args: argparse.Namespace) -> int:
    from .rename import apply, plan, undo

    if args.undo:
        if args.paths:
            _say("错误：用 --undo 的时候，不要再写文件或文件夹")
            return EXIT_ERROR
        try:
            outcome = undo(args.undo)
        except ValueError as exc:
            _say(f"错误：{exc}")
            return EXIT_ERROR
        for old, new in outcome.done:
            print(f"{old.name}\n  → {new.name}")
        print(f"\n已改回 {len(outcome.done)} 个文件。")
        for old, new, reason in outcome.failed:
            _say(f"没能把 {old} 改回 {new.name}：{reason}")
        return EXIT_ERROR if outcome.failed else EXIT_OK

    if not args.paths:
        _say("错误：请写上要改名的文件或文件夹，例如 ofdkit rename 发票文件夹")
        return EXIT_ERROR
    try:
        renames = plan(args.paths, args.pattern, args.recursive, companions=not args.only_ofd)
    except ValueError as exc:
        _say(f"错误：{exc}")
        return EXIT_ERROR

    planned = [rename for rename in renames if rename.target is not None]
    skipped = [rename for rename in renames if rename.target is None]
    if planned and not args.apply:
        print("预览（还没有改名）：\n")
    for rename in planned:
        assert rename.target is not None
        print(f"{rename.source}\n  → {rename.target.name}" + ("（和别的文件是同一张发票）" if rename.duplicate else ""))
        for old, new in rename.companions:
            print(f"  同名的 {old.name} 也改成 {new.name}")
    if skipped:
        print("\n不改名的文件：")
        for rename in skipped:
            print(f"  {rename.source}：{rename.skipped}")
    if not planned:
        print("\n没有需要改名的文件。")
        return EXIT_OK

    companions = sum(len(rename.companions) for rename in planned)
    extra = f"（另外还有 {companions} 个同名的 PDF、XML 等文件）" if companions else ""
    if not args.apply:
        command = " ".join(
            [
                "ofdkit rename",
                *(_quote(path) for path in args.paths),
                *(["-r"] if args.recursive else []),
                *(["--pattern", _quote(args.pattern)] if args.pattern != DEFAULT_PATTERN else []),
                *(["--only-ofd"] if args.only_ofd else []),
                "--apply",
            ]
        )
        print(f"\n共 {len(planned)} 个发票文件会改名{extra}。以上只是预览，还没有改。")
        print(f"确认没问题的话，加上 --apply 再运行一次：\n{command}")
        return EXIT_OK

    outcome = apply(planned)
    print(f"\n已改名 {len(outcome.done)} 个文件。")
    for old, new, reason in outcome.failed:
        _say(f"没能把 {old} 改成 {new.name}：{reason}")
    if outcome.log is not None:
        print(f"改名记录保存在 {outcome.log}\n要改回原来的名字，运行：ofdkit rename --undo {_quote(str(outcome.log))}")
    return EXIT_ERROR if outcome.failed else EXIT_OK


def _describe(args: argparse.Namespace) -> int:
    from .describe import describe

    text = json.dumps(describe(args.file), ensure_ascii=False, indent=1)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        _say(f"已保存到 {args.output}。文字、文件名和号码已经打码，但打码不能保证万无一失，分享之前请再检查一遍。")
    else:
        print(text)
    return EXIT_OK


def _mcp(args: argparse.Namespace) -> int:
    try:
        from .mcp_server import create_server
    except ImportError as exc:
        _say(f'错误：MCP 功能需要先安装：pip install "ofdkit[mcp]"（{exc}）')
        return EXIT_ERROR
    create_server(root=args.root).run("stdio")
    return EXIT_OK


def _add_buyer_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--buyer",
        action="append",
        default=[],
        metavar="公司名或税号",
        help="检查发票抬头：购买方不是这个公司（或税号）的发票会标出来。名称和税号都要查的话，写两次 --buyer",
    )


def _quote(text: str) -> str:
    return f'"{text}"' if any(char in text for char in " &()") else text


def _write_csv(stream: Any, rows: list[dict[str, Any]]) -> None:
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)


def _say(message: str) -> None:
    print(f"ofdkit: {message}", file=sys.stderr)


def _silence_stdout() -> None:
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):  # no real file descriptor, as in tests
        pass


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
