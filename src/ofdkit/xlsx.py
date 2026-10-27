"""Invoice summaries as an Excel workbook (.xlsx), written with the standard library only.

CSV loses information when Excel opens it: a 20-digit 数电票 number becomes
``2.44E+19`` and leading zeros of invoice codes disappear. The workbook stores numbers
that are really identifiers as text, amounts as numbers, and dates as dates, so they
can be added up, sorted and filtered.

Two sheets: 发票 (one row per file, with totals) and 明细 (one row per line item).
"""

from __future__ import annotations

import datetime as dt
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import IO, Any
from unicodedata import east_asian_width
from xml.sax.saxutils import escape

from .batch import InvoiceFile, item_names, problems, summary
from .invoice import Invoice, LineItem

#: Kinds of cell. ``text`` keeps digits as typed; ``money`` and ``number`` are numeric.
TEXT, INTEGER, MONEY, NUMBER, DATE = "text", "integer", "money", "number", "date"

# Row colours: header, a duplicate invoice, a file without invoice data, an unreadable file,
# an invoice for another buyer.
_FILLS = {"header": "DDEBF7", "duplicate": "FFF2CC", "not_invoice": "F2F2F2", "error": "FCE4E4", "mismatch": "FCE4D6"}
_NUMBER_FORMATS = {TEXT: 49, INTEGER: 1, MONEY: 4, NUMBER: 0, DATE: 164}  # 164 is yyyy-mm-dd, below
_MAX_CELL_TEXT = 32_767  # Excel's limit
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_EXCEL_EPOCH = dt.date(1899, 12, 30)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass
class _Cell:
    value: Any
    kind: str = TEXT
    formula: str | None = None
    bold: bool = False


@dataclass
class _Sheet:
    name: str
    header: list[str]
    kinds: list[str]
    rows: list[tuple[list[_Cell], str | None]]  # cells and the row's fill


def write_invoices_xlsx(results: Sequence[InvoiceFile], target: str | Path | IO[bytes]) -> None:
    """Write the results of :func:`ofdkit.read_invoices` as an Excel workbook."""
    sheets = [_invoice_sheet(results), _item_sheet(results)]
    _write_workbook(sheets, target)


# The 发票 sheet: header, getter and kind for each column.
_INVOICE_COLUMNS: list[tuple[str, Callable[[Invoice], Any], str]] = [
    ("开票日期", lambda i: i.issue_date, DATE),
    ("发票号码", lambda i: i.invoice_number, TEXT),
    ("发票代码", lambda i: i.invoice_code, TEXT),
    ("发票种类", lambda i: i.invoice_type, TEXT),
    ("销售方名称", lambda i: i.seller.name, TEXT),
    ("销售方纳税人识别号", lambda i: i.seller.tax_id, TEXT),
    ("购买方名称", lambda i: i.buyer.name, TEXT),
    ("购买方纳税人识别号", lambda i: i.buyer.tax_id, TEXT),
    ("商品或服务", lambda i: item_names(i, limit=5), TEXT),
    ("金额", lambda i: i.amount_without_tax, MONEY),
    ("税额", lambda i: i.tax_amount, MONEY),
    ("价税合计", lambda i: i.total_amount, MONEY),
]

_ITEM_COLUMNS: list[tuple[str, Callable[[LineItem], Any], str]] = [
    ("名称", lambda item: item.name, TEXT),
    ("规格型号", lambda item: item.specification, TEXT),
    ("单位", lambda item: item.unit, TEXT),
    ("数量", lambda item: item.quantity, NUMBER),
    ("单价", lambda item: item.unit_price, NUMBER),
    ("金额", lambda item: item.amount, MONEY),
    ("税率", lambda item: item.tax_rate, TEXT),
    ("税额", lambda item: item.tax_amount, MONEY),
]


def _invoice_sheet(results: Sequence[InvoiceFile]) -> _Sheet:
    header = ["序号", *(name for name, _, _ in _INVOICE_COLUMNS), "提醒", "文件"]
    kinds = [INTEGER, *(kind for _, _, kind in _INVOICE_COLUMNS), TEXT, TEXT]
    rows: list[tuple[list[_Cell], str | None]] = []
    for number, result in enumerate(results, start=1):
        invoice = result.invoice
        values = [getter(invoice) if invoice else None for _, getter, _ in _INVOICE_COLUMNS]
        cells = [_Cell(number, INTEGER), *(_Cell(v, k) for v, (_, _, k) in zip(values, _INVOICE_COLUMNS))]
        cells += [_Cell("；".join(problems(result))), _Cell(result.file)]
        if invoice is None:
            fill = "not_invoice" if problems(result)[0].startswith("不是发票") else "error"
        elif result.buyer_mismatch:
            fill = "mismatch"
        else:
            fill = "duplicate" if result.duplicate else None
        rows.append((cells, fill))

    if results:
        totals = summary(results)
        money = {name: index for index, name in enumerate(header) if name in ("金额", "税额", "价税合计")}
        sums = {"金额": totals["amount_without_tax_sum"], "税额": totals["tax_amount_sum"], "价税合计": totals["total_amount_sum"]}
        cells = [_Cell(None) for _ in header]
        cells[0] = _Cell("合计", bold=True)
        for name, index in money.items():
            column = _column_letter(index)
            cells[index] = _Cell(sums[name], MONEY, formula=f"SUBTOTAL(109,{column}2:{column}{len(results) + 1})", bold=True)
        rows.append((cells, None))
        if totals["duplicates"]:
            cells = [_Cell(None) for _ in header]
            cells[0] = _Cell("合计（重复的发票只算一次）", bold=True)
            cells[money["价税合计"]] = _Cell(totals["total_amount_sum_without_duplicates"], MONEY, bold=True)
            rows.append((cells, None))
    return _Sheet("发票", header, kinds, rows)


def _item_sheet(results: Sequence[InvoiceFile]) -> _Sheet:
    header = ["发票序号", "发票号码", "开票日期", "销售方名称", *(name for name, _, _ in _ITEM_COLUMNS)]
    kinds = [INTEGER, TEXT, DATE, TEXT, *(kind for _, _, kind in _ITEM_COLUMNS)]
    rows: list[tuple[list[_Cell], str | None]] = []
    for number, result in enumerate(results, start=1):
        invoice = result.invoice
        if invoice is None:
            continue
        for item in invoice.items:
            cells = [
                _Cell(number, INTEGER),
                _Cell(invoice.invoice_number),
                _Cell(invoice.issue_date, DATE),
                _Cell(invoice.seller.name),
                *(_Cell(getter(item), kind) for _, getter, kind in _ITEM_COLUMNS),
            ]
            rows.append((cells, "duplicate" if result.duplicate else None))
    return _Sheet("明细", header, kinds, rows)


def _write_workbook(sheets: list[_Sheet], target: str | Path | IO[bytes]) -> None:
    strings: dict[str, int] = {}
    styles = _Styles()
    worksheets = [_worksheet_xml(sheet, index == 0, strings, styles) for index, sheet in enumerate(sheets)]

    sheet_entries = "".join(
        f'<sheet name="{_attr(sheet.name)}" sheetId="{n}" r:id="rId{n}"/>' for n, sheet in enumerate(sheets, start=1)
    )
    defined = "".join(
        f'<definedName name="_xlnm._FilterDatabase" localSheetId="{n}" hidden="1">'
        f"{_text(_quote_sheet(sheet.name))}!$A$1:${_column_letter(len(sheet.header) - 1)}${_data_rows(sheet) + 1}</definedName>"
        for n, sheet in enumerate(sheets)
    )
    workbook = (
        f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><bookViews><workbookView/></bookViews>'
        f"<sheets>{sheet_entries}</sheets><definedNames>{defined}</definedNames></workbook>"
    )
    workbook_rels = "".join(
        f'<Relationship Id="rId{n}" Type="{_REL}/worksheet" Target="worksheets/sheet{n}.xml"/>'
        for n in range(1, len(sheets) + 1)
    )
    count = len(sheets)
    workbook_rels += (
        f'<Relationship Id="rId{count + 1}" Type="{_REL}/styles" Target="styles.xml"/>'
        f'<Relationship Id="rId{count + 2}" Type="{_REL}/sharedStrings" Target="sharedStrings.xml"/>'
    )
    shared = "".join(f'<si><t xml:space="preserve">{_text(value)}</t></si>' for value in strings)
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{n}.xml" ContentType="{_CT}.worksheet+xml"/>'
        for n in range(1, len(sheets) + 1)
    )

    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{_CT}.sheet.main+xml"/>'
            f'<Override PartName="/xl/styles.xml" ContentType="{_CT}.styles+xml"/>'
            f'<Override PartName="/xl/sharedStrings.xml" ContentType="{_CT}.sharedStrings+xml"/>'
            f"{overrides}</Types>"
        ),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{workbook_rels}</Relationships>'
        ),
        "xl/styles.xml": styles.xml(),
        "xl/sharedStrings.xml": f'<sst xmlns="{_MAIN}" count="{len(strings)}" uniqueCount="{len(strings)}">{shared}</sst>',
        **{f"xl/worksheets/sheet{n}.xml": xml for n, xml in enumerate(worksheets, start=1)},
    }
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, xml in parts.items():
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + xml)


def _worksheet_xml(sheet: _Sheet, selected: bool, strings: dict[str, int], styles: _Styles) -> str:
    widths = [_display_width(name) for name in sheet.header]
    xml_rows = []
    header_cells = "".join(
        _cell_xml(f"{_column_letter(i)}1", _Cell(name, bold=True), styles.index(TEXT, "header", True), strings)
        for i, name in enumerate(sheet.header)
    )
    xml_rows.append(f'<row r="1">{header_cells}</row>')
    for number, (cells, fill) in enumerate(sheet.rows, start=2):
        parts = []
        for i, cell in enumerate(cells):
            kind = cell.kind if cell.value is not None else sheet.kinds[i]
            value = _convert(cell.value, kind)
            if value is None and cell.value is not None:  # not a number or date after all
                kind, value = TEXT, str(cell.value)
            reference = f"{_column_letter(i)}{number}"
            parts.append(_cell_xml(reference, _Cell(value, kind, cell.formula), styles.index(kind, fill, cell.bold), strings))
            if value is not None and not (cell.bold and kind == TEXT):  # labels of totals may overflow
                widths[i] = max(widths[i], _display_width(_shown(value, kind)))
        xml_rows.append(f'<row r="{number}">{"".join(parts)}</row>')

    last_column = _column_letter(len(sheet.header) - 1)
    last_row = len(sheet.rows) + 1
    cols = "".join(
        f'<col min="{i}" max="{i}" width="{min(max(width, 6), 60) + 2}" customWidth="1"/>' for i, width in enumerate(widths, start=1)
    )
    tab = ' tabSelected="1"' if selected else ""
    view = (
        f'<sheetView workbookViewId="0"{tab}>'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView>'
    )
    return (
        f'<worksheet xmlns="{_MAIN}" xmlns:r="{_REL}">'
        f'<dimension ref="A1:{last_column}{last_row}"/><sheetViews>{view}</sheetViews>'
        f'<sheetFormatPr defaultRowHeight="15"/><cols>{cols}</cols>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        f'<autoFilter ref="A1:{last_column}{_data_rows(sheet) + 1}"/>'
        f'<ignoredErrors><ignoredError sqref="A1:{last_column}{last_row}" numberStoredAsText="1"/></ignoredErrors>'
        "</worksheet>"
    )


def _cell_xml(reference: str, cell: _Cell, style: int, strings: dict[str, int]) -> str:
    if cell.value is None and cell.formula is None:
        return f'<c r="{reference}" s="{style}"/>'
    if cell.kind == TEXT:
        index = strings.setdefault(_clean(str(cell.value)), len(strings))
        return f'<c r="{reference}" s="{style}" t="s"><v>{index}</v></c>'
    formula = f"<f>{_text(cell.formula)}</f>" if cell.formula else ""
    value = f"<v>{cell.value}</v>" if cell.value is not None else ""
    return f'<c r="{reference}" s="{style}">{formula}{value}</c>'


def _convert(value: Any, kind: str) -> Any:
    """The value as written into the sheet: a number for numeric kinds, a serial for dates."""
    if value is None or value == "":
        return None
    if kind == TEXT:
        return str(value)
    if kind == INTEGER:
        return int(value)
    if kind == DATE:
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(value))
        if not match:
            return None
        try:
            return (dt.date(*map(int, match.groups())) - _EXCEL_EPOCH).days
        except ValueError:
            return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return format(number, "f") if number.is_finite() else None


def _shown(value: Any, kind: str) -> str:
    """Roughly how the value looks in Excel, to size the column."""
    if kind == DATE:
        return "2000-01-01"
    if kind == MONEY:
        return f"{Decimal(value):,.2f}"
    return str(value)


class _Styles:
    """Cell formats, created as cells ask for them."""

    def __init__(self) -> None:
        self._formats: dict[tuple[str, str | None, bool], int] = {(TEXT, None, False): 0}

    def index(self, kind: str, fill: str | None, bold: bool) -> int:
        return self._formats.setdefault((kind, fill, bold), len(self._formats))

    def xml(self) -> str:
        fill_ids = {name: n for n, name in enumerate(_FILLS, start=2)}  # 0 and 1 are reserved
        fills = '<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        fills += "".join(
            f'<fill><patternFill patternType="solid"><fgColor rgb="FF{rgb}"/><bgColor indexed="64"/></patternFill></fill>'
            for rgb in _FILLS.values()
        )
        xfs = []
        for kind, fill, bold in self._formats:
            number_format = _NUMBER_FORMATS[kind]
            fill_id = fill_ids[fill] if fill else 0
            xfs.append(
                f'<xf numFmtId="{number_format}" fontId="{int(bold)}" fillId="{fill_id}" borderId="0" xfId="0"'
                f' applyNumberFormat="1" applyFont="1" applyFill="1"/>'
            )
        font = '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        bold_font = '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        return (
            f'<styleSheet xmlns="{_MAIN}">'
            '<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts>'
            f'<fonts count="2">{font}{bold_font}</fonts>'
            f'<fills count="{len(_FILLS) + 2}">{fills}</fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        )


def _data_rows(sheet: _Sheet) -> int:
    """Rows above the totals, which the filter covers."""
    return sum(1 for cells, _ in sheet.rows if not any(cell.bold for cell in cells))


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _display_width(text: str) -> int:
    return sum(2 if east_asian_width(char) in "WF" else 1 for char in text)


def _clean(text: str) -> str:
    return _ILLEGAL_XML.sub("", text)[:_MAX_CELL_TEXT]


def _text(text: str) -> str:
    return escape(_clean(text))


def _attr(text: str) -> str:
    return escape(_clean(text), {'"': "&quot;"})


def _quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml"
