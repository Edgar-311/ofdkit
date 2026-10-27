"""Plain-text reports in Chinese for people reading a terminal: ``ofdkit show``."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from unicodedata import east_asian_width

from .batch import InvoiceFile, problems
from .invoice import Invoice

#: Line items listed by :func:`invoice_report` before the rest are only counted.
MAX_ITEMS_SHOWN = 10


def invoice_report(invoice: Invoice, problems_found: Sequence[str] = ()) -> str:
    """One invoice as aligned label-value lines, the way it reads on paper."""
    lines: list[tuple[str, str]] = []

    def add(label: str, value: str | None) -> None:
        if value:
            lines.append((label, value))

    add("发票号码", invoice.invoice_number)
    add("发票代码", invoice.invoice_code)
    add("开票日期", invoice.issue_date)
    for label, party in (("购买方", invoice.buyer), ("销售方", invoice.seller)):
        add(label, party.name)
        add("" if party.name else label, f"税号 {party.tax_id}" if party.tax_id else None)
    add("金额", money(invoice.amount_without_tax))
    add("税额", money(invoice.tax_amount))
    add("价税合计", money(invoice.total_amount))
    item_lines: list[list[Any]] = []  # identical lines next to each other are shown once
    for item in invoice.items:
        line = "  ".join(part for part in (item.name or "（没有名称）", money(item.amount), item.tax_rate) if part)
        if item_lines and item_lines[-1][0] == line:
            item_lines[-1][1] += 1
        else:
            item_lines.append([line, 1])
    for number, (line, count) in enumerate(item_lines[:MAX_ITEMS_SHOWN]):
        add("明细" if number == 0 else "", line + (f"（{count} 行相同）" if count > 1 else ""))
    if len(item_lines) > MAX_ITEMS_SHOWN:
        add("", f"……还有 {len(item_lines) - MAX_ITEMS_SHOWN} 行，完整内容请用 ofdkit invoice 查看")
    add("备注", " ".join((invoice.note or "").split()))
    add("开票人", invoice.issuer)
    for index, problem in enumerate(problems_found):
        add("提醒" if index == 0 else "", problem)

    width = max((display_width(label) for label, _ in lines), default=0) + 2
    body = "\n".join(pad(label, width) + value for label, value in lines)
    return f"{invoice.invoice_type or '发票'}\n\n{body}"


def table_report(results: Sequence[InvoiceFile]) -> str:
    """One line per file: number, date, invoice number, seller, total, problems, file."""
    header = ["序号", "开票日期", "发票号码", "销售方", "价税合计", "提醒", "文件"]
    rows = []
    for number, result in enumerate(results, start=1):
        invoice = result.invoice
        short = "；".join(dict.fromkeys(re.split(r"[（：]", problem, maxsplit=1)[0] for problem in problems(result)))
        if invoice is None:
            rows.append([str(number), "", "", "", "", short, result.file])
            continue
        rows.append(
            [
                str(number),
                invoice.issue_date or "",
                invoice.invoice_number or "",
                truncate(invoice.seller.name or "", 24),
                money(invoice.total_amount) or "",
                short,
                result.file,
            ]
        )
    right_aligned = {0, 4}
    widths = [max(display_width(row[i]) for row in [header, *rows]) for i in range(len(header))]
    lines = []
    for row in [header, *rows]:
        cells = [
            pad(cell, widths[i], right=i in right_aligned) if i < len(row) - 1 else cell for i, cell in enumerate(row)
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def summary_text(totals: dict[str, Any]) -> str:
    """The counts and sums from :func:`ofdkit.batch.summary` as a sentence or two."""
    counts = [f"{totals['invoices']} 张发票"]
    if totals["without_invoice_data"]:
        counts.append(f"{totals['without_invoice_data']} 个不是发票")
    if totals["errors"]:
        counts.append(f"{totals['errors']} 个读不出来")
    text = f"共 {totals['files']} 个文件：{'，'.join(counts)}。"
    if totals["invoices"]:
        parts = [
            f"{label} {money(totals[key])}"
            for label, key in (("金额", "amount_without_tax_sum"), ("税额", "tax_amount_sum"))
            if Decimal(totals[key])  # left out when no invoice has the field
        ]
        text += f"\n价税合计 {money(totals['total_amount_sum'])} 元" + (f"（{'，'.join(parts)}）" if parts else "") + "。"
    for column, label in (("total_amount", "价税合计"), ("amount_without_tax", "金额"), ("tax_amount", "税额")):
        counts = totals.get("not_summed", {}).get(column, {})
        parts = [f"{counts[key]} 张{word}" for key, word in (("invalid", "不是数字"), ("missing", "缺少")) if counts.get(key)]
        if parts:
            text += f"\n注意：{label}有 {'、'.join(parts)}，这些没有算进上面的合计。"
    if totals.get("buyer_mismatches"):
        text += f"\n有 {totals['buyer_mismatches']} 张发票的购买方不对（抬头或税号和你指定的不一样），请看“提醒”一栏。"
    if totals["duplicates"]:
        text += (
            f"\n有 {totals['duplicates']} 个文件和别的文件是同一张发票（发票号码相同），"
            f"重复的只算一次的话，价税合计 {money(totals['total_amount_sum_without_duplicates'])} 元。"
        )
    return text


def money(value: str | None) -> str | None:
    """``4449.00`` as ``4,449.00``; values that are not numbers are returned as they are."""
    if not value:
        return value
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, ValueError):
        return value


def display_width(text: str) -> int:
    """Columns the text takes in a terminal: Chinese characters take two."""
    return sum(2 if east_asian_width(char) in "WF" else 1 for char in text)


def pad(text: str, width: int, right: bool = False) -> str:
    space = " " * max(width - display_width(text), 0)
    return space + text if right else text + space


def truncate(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    kept = ""
    for char in text:
        if display_width(kept + char) > width - 1:
            break
        kept += char
    return kept + "…"
