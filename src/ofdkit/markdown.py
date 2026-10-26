"""Markdown output: the document's text, plus an invoice summary table for e-invoices."""

from __future__ import annotations

import re

from .document import OFDDocument
from .errors import OFDError
from .invoice import Invoice

_INVOICE_ROWS = [
    ("发票号码", lambda i: i.invoice_number),
    ("发票代码", lambda i: i.invoice_code),
    ("发票种类", lambda i: i.invoice_type),
    ("开票日期", lambda i: i.issue_date),
    ("校验码", lambda i: i.check_code),
    ("购买方名称", lambda i: i.buyer.name),
    ("购买方纳税人识别号", lambda i: i.buyer.tax_id),
    ("购买方地址电话", lambda i: i.buyer.address_phone),
    ("购买方开户行及账号", lambda i: i.buyer.bank_account),
    ("销售方名称", lambda i: i.seller.name),
    ("销售方纳税人识别号", lambda i: i.seller.tax_id),
    ("销售方地址电话", lambda i: i.seller.address_phone),
    ("销售方开户行及账号", lambda i: i.seller.bank_account),
    ("合计金额", lambda i: i.amount_without_tax),
    ("合计税额", lambda i: i.tax_amount),
    ("价税合计", lambda i: i.total_amount),
    ("开票人", lambda i: i.issuer),
    ("收款人", lambda i: i.payee),
    ("复核人", lambda i: i.reviewer),
    ("备注", lambda i: i.note),
]
_ITEM_COLUMNS = [
    ("项目名称", "name"),
    ("规格型号", "specification"),
    ("单位", "unit"),
    ("数量", "quantity"),
    ("单价", "unit_price"),
    ("金额", "amount"),
    ("税率", "tax_rate"),
    ("税额", "tax_amount"),
]
_INLINE_SPECIAL = re.compile(r"([\\`*_])")
_LINE_START_SPECIAL = re.compile(r"^(\s*)([#>])", re.MULTILINE)


def document_markdown(document: OFDDocument) -> str:
    """Markdown for a whole document.

    E-invoices start with a table of their fields. Multi-page documents get a heading per
    page. Characters that Markdown would treat as formatting are escaped, so that invoice
    item names such as ``*信息技术服务*`` keep their asterisks.
    """
    sections: list[str] = []
    invoice = document.invoice()
    if invoice is not None:
        sections.append(invoice_markdown(invoice))

    pages = document.pages
    use_headings = invoice is not None or len(pages) > 1
    for page in pages:
        try:
            text = escape(page.text())
        except OFDError as exc:
            document.warnings.append(f"page {page.index + 1}: {exc}")
            text = ""
        if use_headings:
            heading = f"## 第 {page.index + 1} 页" if len(pages) > 1 else "## 原文"
            sections.append(f"{heading}\n\n{text}".rstrip())
        elif text:
            sections.append(text)
    return "\n\n".join(sections).strip() + "\n"


def invoice_markdown(invoice: Invoice) -> str:
    """A Markdown table of the invoice's fields, followed by its line items."""
    lines = ["## 发票信息", "", "| 项目 | 内容 |", "| --- | --- |"]
    for label, get in _INVOICE_ROWS:
        value = get(invoice)
        if value:
            lines.append(f"| {label} | {_cell(value)} |")
    if invoice.items:
        lines += ["", "### 明细", ""]
        columns = [(label, attribute) for label, attribute in _ITEM_COLUMNS if any(getattr(item, attribute) for item in invoice.items)]
        lines.append("| " + " | ".join(label for label, _ in columns) + " |")
        lines.append("|" + " --- |" * len(columns))
        for item in invoice.items:
            lines.append("| " + " | ".join(_cell(getattr(item, attribute) or "") for _, attribute in columns) + " |")
    if invoice.warnings:
        lines += ["", *[f"> 注意：{escape(warning)}" for warning in invoice.warnings]]
    return "\n".join(lines)


def escape(text: str) -> str:
    """Escape characters that would turn plain text into Markdown formatting."""
    text = _INLINE_SPECIAL.sub(r"\\\1", text)
    return _LINE_START_SPECIAL.sub(r"\1\\\2", text)


def _cell(value: str) -> str:
    return escape(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
