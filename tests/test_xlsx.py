"""The Excel workbook written by ``ofdkit batch -o 汇总.xlsx``."""

import io
import unittest
import xml.etree.ElementTree as ET
import zipfile

from ofdkit.batch import InvoiceFile
from ofdkit.invoice import Invoice, LineItem, Party
from ofdkit.xlsx import write_invoices_xlsx

try:
    import openpyxl
except ImportError:  # only used to check that the workbook reads back; not a dependency
    openpyxl = None

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
LONG_NUMBER = "00000000000000000001"  # 20 digits: Excel turns this into 1 when it is a number


def results():
    invoice = Invoice(
        invoice_number=LONG_NUMBER,
        invoice_code="000000000001",
        invoice_type="电子发票（普通发票）",
        issue_date="2026-01-02",
        seller=Party(name="测试单位乙", tax_id="TESTSELLER0002"),
        buyer=Party(name="测试单位甲"),
        amount_without_tax="100.00",
        tax_amount="6.00",
        total_amount="106.00",
        items=[LineItem(name="*测试*服务", quantity="2", unit_price="50", amount="100.00", tax_rate="6%", tax_amount="6.00")],
    )
    copy = Invoice(invoice_number=LONG_NUMBER, invoice_code="000000000001", issue_date="2026年1月", total_amount="106.00")
    return [
        InvoiceFile("a.ofd", invoice=invoice, duplicate=True),
        InvoiceFile("b.ofd", invoice=copy, duplicate=True),
        InvoiceFile("c.ofd", error="no invoice data"),
        InvoiceFile("d.ofd", error="not an OFD file (not a ZIP container): bad"),
    ]


class WorkbookXmlTest(unittest.TestCase):
    """Checks on the raw parts, so the test runs without any third-party package."""

    def setUp(self):
        buffer = io.BytesIO()
        write_invoices_xlsx(results(), buffer)
        self.archive = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
        self.strings = [
            "".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t"))
            for si in ET.fromstring(self.archive.read("xl/sharedStrings.xml"))
        ]

    def cells(self, sheet):
        root = ET.fromstring(self.archive.read(f"xl/worksheets/sheet{sheet}.xml"))
        found = {}
        for cell in root.iterfind(".//m:c", NS):
            value = cell.find("m:v", NS)
            formula = cell.find("m:f", NS)
            text = value.text if value is not None else None
            if cell.get("t") == "s":
                text = self.strings[int(text)]
            found[cell.get("r")] = (text, cell.get("t"), formula.text if formula is not None else None, cell.get("s"))
        return root, found

    def test_every_part_is_well_formed_xml(self):
        for name in self.archive.namelist():
            ET.fromstring(self.archive.read(name))
        self.assertIn("xl/worksheets/sheet2.xml", self.archive.namelist())

    def test_sheet_names(self):
        workbook = ET.fromstring(self.archive.read("xl/workbook.xml"))
        self.assertEqual([s.get("name") for s in workbook.iterfind(".//m:sheet", NS)], ["发票", "明细"])

    def test_identifiers_are_text_and_amounts_are_numbers(self):
        _, cells = self.cells(1)
        self.assertEqual(cells["A1"][0], "序号")
        self.assertEqual(cells["C1"][0], "发票号码")
        self.assertEqual(cells["C2"][:2], (LONG_NUMBER, "s"))
        self.assertEqual(cells["D2"][:2], ("000000000001", "s"))
        self.assertEqual(cells["M2"][:2], ("106.00", None))
        self.assertEqual(cells["B2"][:2], ("46024", None), "2026-01-02 as an Excel date")
        self.assertEqual(cells["B3"][:2], ("2026年1月", "s"), "a date that cannot be read stays text")

    def test_problems_and_files(self):
        _, cells = self.cells(1)
        self.assertEqual(cells["N2"][0], "发票号码重复")
        self.assertEqual(cells["N4"][0], "不是发票（没有发票数据）")
        self.assertTrue(cells["N5"][0].startswith("读不出来"))
        self.assertEqual(cells["O5"][0], "d.ofd")

    def test_rows_are_coloured_by_problem(self):
        _, cells = self.cells(1)
        styles = {row: cells[f"O{row}"][3] for row in (2, 4, 5)}
        self.assertEqual(len(set(styles.values())), 3, "duplicate, not an invoice and unreadable differ")

    def test_totals(self):
        root, cells = self.cells(1)
        self.assertEqual(cells["A6"][0], "合计")
        self.assertEqual(cells["M6"][1:3], (None, "SUBTOTAL(109,M2:M5)"))
        self.assertEqual(cells["M6"][0], "212.00")
        self.assertEqual(cells["A7"][0], "合计（重复的发票只算一次）")
        self.assertEqual(cells["M7"][0], "106.00")
        self.assertEqual(root.find("m:autoFilter", NS).get("ref"), "A1:O5", "the filter leaves the totals out")
        self.assertEqual(root.find(".//m:pane", NS).get("state"), "frozen")

    def test_item_sheet(self):
        _, cells = self.cells(2)
        self.assertEqual([cells[f"{c}1"][0] for c in "ABCDE"], ["发票序号", "发票号码", "开票日期", "销售方名称", "名称"])
        self.assertEqual(cells["B2"][:2], (LONG_NUMBER, "s"))
        self.assertEqual(cells["E2"][0], "*测试*服务")
        self.assertEqual(cells["H2"][:2], ("2", None))
        self.assertNotIn("A3", cells, "the copy has no items")

    def test_empty_results(self):
        buffer = io.BytesIO()
        write_invoices_xlsx([], buffer)
        archive = zipfile.ZipFile(buffer)
        for name in archive.namelist():
            ET.fromstring(archive.read(name))

    def test_control_characters_are_removed(self):
        buffer = io.BytesIO()
        write_invoices_xlsx([InvoiceFile("a\x0bb.ofd", error="x\x01y")], buffer)
        archive = zipfile.ZipFile(buffer)
        ET.fromstring(archive.read("xl/sharedStrings.xml"))


@unittest.skipIf(openpyxl is None, "openpyxl is not installed")
class OpenpyxlTest(unittest.TestCase):
    def test_reads_back(self):
        buffer = io.BytesIO()
        write_invoices_xlsx(results(), buffer)
        buffer.seek(0)
        workbook = openpyxl.load_workbook(buffer)
        sheet = workbook["发票"]
        self.assertEqual(sheet["C2"].value, LONG_NUMBER)
        self.assertEqual(sheet["M2"].value, 106)
        self.assertEqual(sheet["M2"].number_format, "#,##0.00")
        self.assertEqual(sheet["B2"].value.date().isoformat(), "2026-01-02")
        self.assertEqual(sheet["M6"].value, "=SUBTOTAL(109,M2:M5)")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(workbook["明细"]["E2"].value, "*测试*服务")


if __name__ == "__main__":
    unittest.main()
