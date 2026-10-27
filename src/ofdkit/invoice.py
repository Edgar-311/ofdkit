"""Invoice fields from Chinese e-invoices in OFD format.

Three places in an OFD file can carry invoice data, read in this order of trust:

1. An XML attachment with the invoice itself (``Attachs/original_invoice.xml`` in older
   e-invoices), which holds the values directly.
2. Custom tags (``Tags/CustomTags.xml``): each field points at the text objects on the
   page that show its value. Both the 2016/2019 e-invoice schema (``fp:eInvoice``) and
   the layout used by fully digitalised invoices (数电票, ``ofd:root``) are supported.
3. ``CustomData`` entries in OFD.xml, which 数电票 use for a few key fields.

ofdkit only reads these values. It never checks them against the tax authority, so a
result says what the file contains, not that the invoice is genuine.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from ._xml import child_text, children, local_name
from .errors import OFDError

if TYPE_CHECKING:
    from .document import OFDDocument

# Leaf element names of the e-invoice schemas, mapped to Invoice attributes.
_FIELDS = {
    "InvoiceNo": "invoice_number",
    "InvoiceCode": "invoice_code",
    "IssueDate": "issue_date",
    "InvoiceCheckCode": "check_code",
    "MachineNo": "machine_number",
    "TaxExclusiveTotalAmount": "amount_without_tax",
    "TaxTotalAmount": "tax_amount",
    "TaxInclusiveTotalAmount": "total_amount",
    "InvoiceClerk": "issuer",
    "Payee": "payee",
    "Checker": "reviewer",
    "Note": "note",
}
_PARTY_FIELDS = {"Name": "name", "TaxID": "tax_id", "AddrTel": "address_phone", "FinancialAccount": "bank_account"}
_ITEM_FIELDS = {
    "Item": "name",
    "Specification": "specification",
    "MeasurementDimension": "unit",
    "Quantity": "quantity",
    "Price": "unit_price",
    "Amount": "amount",
    "TaxScheme": "tax_rate",
    "TaxAmount": "tax_amount",
}
# CustomData names that e-invoices put in OFD.xml, mapped to schema leaf names.
# Names are compared after removing spaces and punctuation (see _custom_data_key).
_CUSTOM_DATA = {
    "发票号码": "InvoiceNo",
    "发票代码": "InvoiceCode",
    "开票日期": "IssueDate",
    "校验码": "InvoiceCheckCode",
    "机器编号": "MachineNo",
    "合计金额": "TaxExclusiveTotalAmount",
    "合计税额": "TaxTotalAmount",
    "价税合计": "TaxInclusiveTotalAmount",
    "购买方名称": "BuyerName",
    "购买方纳税人识别号": "BuyerTaxID",
    "购买方地址电话": "BuyerAddrTel",
    "购买方开户行及账号": "BuyerFinancialAccount",
    "销售方名称": "SellerName",
    "销售方纳税人识别号": "SellerTaxID",
    "销售方地址电话": "SellerAddrTel",
    "销售方开户行及账号": "SellerFinancialAccount",
    "开票人": "InvoiceClerk",
    "收款人": "Payee",
    "复核人": "Checker",
    "复核": "Checker",
    "备注": "Note",
}
# A source counts as an invoice only if it has at least one of these.
_KEY_FIELDS = ("InvoiceNo", "InvoiceCode", "TaxInclusiveTotalAmount", "TaxExclusiveTotalAmount")

_AMOUNT = re.compile(r"-?\d+(?:\.\d+)?")
#: The invoice-level amounts; a value that is not a plain decimal number gets a warning.
AMOUNT_FIELDS = ("amount_without_tax", "tax_amount", "total_amount")
#: Part of the warning for an amount that is present but not a number, such as "无法识别".
NOT_A_NUMBER = "is not a number"
# Titles printed on e-invoices: 数电票 such as 电子发票（增值税专用发票）, and older ones
# such as 上海增值税电子普通发票 (a province, then the type).
_DIGITAL_TITLE = re.compile(r"电子发票[（(]([^）)]{2,24})[）)]")
_OLDER_TITLE = re.compile(r"([\u4e00-\u9fff]{0,4}增值税电子(?:普通|专用)发票(?:[（(]通行费[）)])?)")
_DATE = re.compile(r"^(\d{4})\s*[年/.-]?\s*(\d{1,2})\s*[月/.-]?\s*(\d{1,2})\s*日?(?:[\sT]+\d{1,2}:\d{2}(?::\d{2})?)?$")


@dataclass
class Party:
    """Buyer (购买方) or seller (销售方)."""

    name: str | None = None
    tax_id: str | None = None
    address_phone: str | None = None
    bank_account: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "tax_id": self.tax_id,
            "address_phone": self.address_phone,
            "bank_account": self.bank_account,
        }


@dataclass
class LineItem:
    """One line of goods or services. Numbers are kept as decimal strings."""

    name: str | None = None
    specification: str | None = None
    unit: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    tax_rate: str | None = None
    tax_amount: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "specification": self.specification,
            "unit": self.unit,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "amount": self.amount,
            "tax_rate": self.tax_rate,
            "tax_amount": self.tax_amount,
        }


@dataclass
class Invoice:
    """Invoice data found in an OFD file.

    Amounts are decimal strings such as ``"4449.00"`` so that no precision is lost.
    ``issue_date`` is ``YYYY-MM-DD`` when the file's date could be read.
    """

    invoice_number: str | None = None
    invoice_code: str | None = None
    #: The invoice type as printed in its title, for example 电子发票（增值税专用发票）.
    invoice_type: str | None = None
    issue_date: str | None = None
    check_code: str | None = None
    machine_number: str | None = None
    buyer: Party = field(default_factory=Party)
    seller: Party = field(default_factory=Party)
    amount_without_tax: str | None = None
    tax_amount: str | None = None
    total_amount: str | None = None
    issuer: str | None = None
    payee: str | None = None
    reviewer: str | None = None
    note: str | None = None
    items: list[LineItem] = field(default_factory=list)
    #: Where the values came from: "attachment", "custom_tags" and/or "custom_data".
    sources: list[str] = field(default_factory=list)
    #: Problems noticed in the data, such as totals that do not add up.
    warnings: list[str] = field(default_factory=list)
    #: Every value found, by element path, for fields this class has no attribute for.
    raw: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "invoice_number": self.invoice_number,
            "invoice_code": self.invoice_code,
            "invoice_type": self.invoice_type,
            "issue_date": self.issue_date,
            "check_code": self.check_code,
            "machine_number": self.machine_number,
            "buyer": self.buyer.to_dict(),
            "seller": self.seller.to_dict(),
            "amount_without_tax": self.amount_without_tax,
            "tax_amount": self.tax_amount,
            "total_amount": self.total_amount,
            "issuer": self.issuer,
            "payee": self.payee,
            "reviewer": self.reviewer,
            "note": self.note,
            "items": [item.to_dict() for item in self.items],
            "sources": list(self.sources),
            "warnings": list(self.warnings),
        }
        if include_raw:
            data["raw"] = {path: list(values) for path, values in self.raw.items()}
        return data


@dataclass
class _Source:
    """Values from one place in the file: leaf path -> values, plus grouped line items."""

    name: str
    values: dict[str, list[str]] = field(default_factory=dict)
    items: list[dict[str, str]] = field(default_factory=list)

    def leaf(self, leaf_name: str) -> list[str]:
        """Values of every path ending in ``leaf_name``."""
        found: list[str] = []
        for path, values in self.values.items():
            if path.rsplit("/", 1)[-1] == leaf_name:
                found.extend(values)
        return found

    def is_invoice(self) -> bool:
        return any(self.leaf(name) for name in _KEY_FIELDS)


def read_invoice(document: OFDDocument) -> Invoice | None:
    """Collect invoice data from an opened document, or None if it holds none."""
    sources = [
        source
        for source in (*_attachment_sources(document), *_tag_sources(document), _custom_data_source(document))
        if source.is_invoice()
    ]
    if not sources:
        return None

    def first(leaf_name: str) -> str | None:
        for source in sources:
            for value in source.leaf(leaf_name):
                if value:
                    return value
        return None

    invoice = Invoice()
    for leaf_name, attribute in _FIELDS.items():
        setattr(invoice, attribute, first(leaf_name))
    for prefix, party in (("Buyer", invoice.buyer), ("Seller", invoice.seller)):
        for suffix, attribute in _PARTY_FIELDS.items():
            setattr(party, attribute, first(prefix + suffix))

    for source in sources:
        items = source.items or _flat_items(source)
        if items:
            invoice.items = [_line_item(item) for item in items]
            break

    for source in sources:
        if source.name not in invoice.sources:
            invoice.sources.append(source.name)
        for path, values in source.values.items():
            invoice.raw.setdefault(path, list(values))

    invoice.invoice_type = _invoice_type(document)
    _normalise(invoice)
    return invoice


def _invoice_type(document: OFDDocument) -> str | None:
    """The title printed on the first page, such as 电子发票（普通发票）, or None."""
    if not document.pages:
        return None
    try:
        text = document.pages[0].text()
    except OFDError:
        return None
    for line in text.splitlines():
        compact = re.sub(r"\s+", "", line)
        match = _DIGITAL_TITLE.search(compact)
        if match:
            return f"电子发票（{match.group(1)}）"
        match = _OLDER_TITLE.fullmatch(compact)  # older titles stand on a line of their own
        if match:
            return match.group(1).replace("(", "（").replace(")", "）")
    return None


def _attachment_sources(document: OFDDocument) -> list[_Source]:
    sources = []
    package = document._package
    for body in document._bodies:
        if body.attachments is None:
            continue
        try:
            listing = package.read_xml(body.attachments)
        except OFDError as exc:
            document.warnings.append(f"attachments: {exc}")
            continue
        for attachment in children(listing, "Attachment"):
            location = child_text(attachment, "FileLoc")
            path = package.resolve(body.attachments, location)
            if path is None or not path.lower().endswith(".xml"):
                continue
            try:
                root = package.read_xml(path)
            except OFDError:
                continue
            sources.append(_read_tree("attachment", root, resolve=None))
    return sources


def _tag_sources(document: OFDDocument) -> list[_Source]:
    sources = []
    package = document._package

    def resolve(page_ref: str | None, object_id: str) -> str | None:
        page = document.page_by_id(page_ref) if page_ref else None
        for candidate in [page] if page is not None else document.pages:
            try:
                text = candidate.object_text(object_id)
            except OFDError:
                continue
            if text is not None:
                return text
        return None

    for body in document._bodies:
        if body.custom_tags is None:
            continue
        try:
            listing = package.read_xml(body.custom_tags)
        except OFDError as exc:
            document.warnings.append(f"custom tags: {exc}")
            continue
        for tag in children(listing, "CustomTag"):
            path = package.resolve(body.custom_tags, child_text(tag, "FileLoc"))
            if path is None:
                continue
            try:
                root = package.read_xml(path)
            except OFDError as exc:
                document.warnings.append(f"custom tags: {exc}")
                continue
            sources.append(_read_tree("custom_tags", root, resolve=resolve))
    return sources


def _custom_data_source(document: OFDDocument) -> _Source:
    source = _Source("custom_data")
    for name, value in document.info.custom_data.items():
        leaf_name = _CUSTOM_DATA.get(_custom_data_key(name))
        if leaf_name and value.strip():
            source.values.setdefault(leaf_name, []).append(value.strip())
    return source


def _custom_data_key(name: str) -> str:
    """``销售方地址、 电话`` and ``销售方地址电话`` name the same field."""
    return re.sub(r"[\s、，,:：]", "", name)


def _read_tree(name: str, root: ET.Element, resolve: Callable[[str | None, str], str | None] | None) -> _Source:
    """Collect leaf values of an invoice XML tree.

    A leaf is an element whose only children are ObjectRef elements (custom tags) or
    that has no children at all (attachments). GoodsInfo elements group line items.
    """
    source = _Source(name)

    def value_of(element: ET.Element) -> str | None:
        references = list(children(element, "ObjectRef"))
        if references and resolve is not None:
            parts = []
            for reference in references:
                object_id = (reference.text or "").strip()
                if object_id:
                    text = resolve(reference.get("PageRef"), object_id)
                    if text:
                        parts.append(text)
            value = "".join(parts).strip()
        else:
            value = (element.text or "").strip()
        return value or None

    def visit(element: ET.Element, path: list[str], depth: int) -> None:
        element_name = local_name(element.tag)
        if not element_name or depth > 16:
            return
        if element_name == "GoodsInfo":
            item: dict[str, str] = {}
            for leaf in element:
                value = value_of(leaf)
                if value is not None:
                    item.setdefault(local_name(leaf.tag), value)
            if item:
                source.items.append(item)
            return
        element_children = [c for c in element if local_name(c.tag) and local_name(c.tag) != "ObjectRef"]
        if not element_children:
            value = value_of(element)
            if value is not None:
                source.values.setdefault("/".join([*path, element_name]), []).append(value)
            return
        for element_child in element_children:
            visit(element_child, [*path, element_name], depth + 1)

    for element_child in root:
        visit(element_child, [], 0)
    return source


def _flat_items(source: _Source) -> list[dict[str, str]]:
    """Line items written as repeated top-level elements (数电票 custom tags)."""
    columns = {leaf: source.values.get(leaf, []) for leaf in _ITEM_FIELDS}
    count = max((len(values) for values in columns.values()), default=0)
    return [
        {leaf: values[index] for leaf, values in columns.items() if index < len(values)}
        for index in range(count)
    ]


def _line_item(values: dict[str, str]) -> LineItem:
    return LineItem(**{attribute: values.get(leaf) for leaf, attribute in _ITEM_FIELDS.items()})


def _normalise(invoice: Invoice) -> None:
    for attribute in AMOUNT_FIELDS:
        value = _amount(getattr(invoice, attribute))
        setattr(invoice, attribute, value)  # kept as found when it is not a number
        if value is not None and parse_amount(value) is None:
            invoice.warnings.append(f"{attribute} {NOT_A_NUMBER}: {value!r}")
    for item in invoice.items:
        item.amount = _amount(item.amount)
        item.tax_amount = _amount(item.tax_amount)
        item.unit_price = _amount(item.unit_price)
        item.quantity = _amount(item.quantity)
    invoice.issue_date = _date(invoice.issue_date)
    for party in (invoice.buyer, invoice.seller):
        if party.tax_id:
            party.tax_id = re.sub(r"\s+", "", party.tax_id).upper()
    if invoice.invoice_number:
        invoice.invoice_number = re.sub(r"\s+", "", invoice.invoice_number)

    totals = [parse_amount(invoice.amount_without_tax), parse_amount(invoice.tax_amount), parse_amount(invoice.total_amount)]
    if all(value is not None for value in totals):
        without_tax, tax, total = totals
        assert without_tax is not None and tax is not None and total is not None
        if without_tax + tax != total:
            invoice.warnings.append(
                f"amount_without_tax + tax_amount != total_amount ({without_tax} + {tax} != {total})"
            )


def _amount(value: str | None) -> str | None:
    """Strip currency signs, thousands separators and spaces from a money value."""
    if value is None:
        return None
    cleaned = re.sub(r"[¥￥,，\s元]", "", value)
    return cleaned if _AMOUNT.fullmatch(cleaned) else value


def parse_amount(value: str | None) -> Decimal | None:
    """The amount as a Decimal, or None when it is missing or not a plain decimal number.

    Only digits with an optional minus sign and decimal point count: ``"0.00"`` is a real
    zero, while ``"无法识别"``, ``"NaN"``, ``"Infinity"`` or ``"1e5"`` are not amounts.
    """
    if value is None or not _AMOUNT.fullmatch(value):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _date(value: str | None) -> str | None:
    """``2024年05月28日``, ``20240528`` or ``2024/5/28`` become ``2024-05-28``."""
    if value is None:
        return None
    match = _DATE.match(value.strip())
    if not match:
        return value
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return value
    return f"{year:04d}-{month:02d}-{day:02d}"
