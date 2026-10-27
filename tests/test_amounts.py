"""Amounts that are missing or not numbers: kept as found, reported, never summed as 0."""

import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import ofdkit
from ofdkit.batch import InvoiceFile, invoice_row, problems, summary
from ofdkit.invoice import NOT_A_NUMBER, Invoice, parse_amount
from ofdkit.report import summary_text
from ofdkit.xlsx import write_invoices_xlsx

from .ofdbuilder import OFDBuilder, Text
from .test_cli import run


def amounts_ofd(number, total=None, without_tax=None, tax=None):
    data = {"发票号码": number}
    for name, value in (("价税合计", total), ("合计金额", without_tax), ("合计税额", tax)):
        if value is not None:
            data[name] = value
    return OFDBuilder(custom_data=data).build([[Text("测试样例", 20, 30)]])


class ParseAmountTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(parse_amount("0.00"), 0)
        self.assertEqual(str(parse_amount("-12.50")), "-12.50")

    def test_not_numbers(self):
        for value in (None, "", "无法识别", "NaN", "nan", "Infinity", "-inf", "1e5", "1E999", "12.", ".5", "1,000.00"):
            self.assertIsNone(parse_amount(value), value)


class MixedAmountsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        files = {
            "1-normal.ofd": amounts_ofd("00000001", "10.60", "10.00", "0.60"),
            "2-zero.ofd": amounts_ofd("00000002", "0.00", "0.00", "0.00"),
            "3-unreadable.ofd": amounts_ofd("00000003", "无法识别", "10.00", "0.60"),
            "4-missing.ofd": amounts_ofd("00000004", None, "5.00", "0.30"),
            "5-nan.ofd": amounts_ofd("00000005", "NaN", "1.00", "0.10"),
            "6-infinity.ofd": amounts_ofd("00000006", "Infinity", "1.00", "0.10"),
        }
        for name, data in files.items():
            (self.root / name).write_bytes(data)
        self.results = ofdkit.read_invoices(self.root)

    def test_values_are_kept_as_found_with_a_warning(self):
        unreadable = self.results[2].invoice
        self.assertEqual(unreadable.total_amount, "无法识别")
        self.assertEqual(unreadable.warnings, [f"total_amount {NOT_A_NUMBER}: '无法识别'"])
        self.assertEqual(self.results[1].invoice.warnings, [], "a real 0 is not a problem")
        self.assertIsNone(self.results[3].invoice.total_amount)

    def test_summary_counts_what_it_could_not_add(self):
        totals = summary(self.results)
        self.assertEqual((totals["invoices"], totals["errors"]), (6, 0))
        self.assertEqual(totals["total_amount_sum"], "10.60")
        self.assertEqual(totals["not_summed"]["total_amount"], {"missing": 1, "invalid": 3})
        self.assertEqual(totals["not_summed"]["amount_without_tax"], {"missing": 0, "invalid": 0})
        self.assertEqual(totals["amount_without_tax_sum"], "27.00")
        rows = [invoice_row(result) for result in self.results]
        self.assertEqual(summary(rows), totals, "rows and results give the same summary")

    def test_reminders_in_chinese(self):
        self.assertEqual(problems(self.results[2]), ["价税合计不是数字（“无法识别”）"])
        self.assertEqual(problems(self.results[3]), ["缺少价税合计"])
        self.assertEqual(problems(self.results[1]), [])
        text = summary_text(summary(self.results))
        self.assertIn("价税合计 10.60 元", text)
        self.assertIn("注意：价税合计有 3 张不是数字、1 张缺少，这些没有算进上面的合计。", text)

    def test_command_line(self):
        code, out, err = run("batch", str(self.root))
        self.assertEqual(code, 0)
        self.assertIn("3 张不是数字、1 张缺少", err)
        self.assertIn("total_amount is not a number: '无法识别'", out)
        out = run(str(self.root / "3-unreadable.ofd"))[1]
        self.assertIn("价税合计  无法识别", out)
        self.assertIn("提醒      价税合计不是数字（“无法识别”）", out)
        data = json.loads(run("invoice", str(self.root / "3-unreadable.ofd"))[1])
        self.assertEqual((data["total_amount"], data["warnings"]), ("无法识别", ["total_amount is not a number: '无法识别'"]))

    def test_excel_keeps_the_text_and_leaves_it_out_of_the_total(self):
        buffer = io.BytesIO()
        write_invoices_xlsx(self.results, buffer)
        archive = zipfile.ZipFile(buffer)
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        strings = ["".join(t.itertext()) for t in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        cells = {}
        for cell in ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).iterfind(".//m:c", ns):
            value = cell.find("m:v", ns)
            text = value.text if value is not None else None
            cells[cell.get("r")] = strings[int(text)] if cell.get("t") == "s" else text
        self.assertEqual(cells["M4"], "无法识别")
        self.assertEqual((cells["M6"], cells["M7"]), ("NaN", "Infinity"), "not numbers, so SUBTOTAL skips them")
        self.assertEqual(cells["M3"], "0.00")
        self.assertEqual(cells["M8"], "10.60", "the total row agrees with the summary")
        self.assertTrue(cells["A9"].startswith("注意：这些金额缺少或不是数字，没有算进合计：价税合计 4 张"))


class ProblemsWithoutAmountsTest(unittest.TestCase):
    def test_missing_amounts_are_named(self):
        self.assertEqual(problems(InvoiceFile("a.ofd", invoice=Invoice())), ["缺少金额", "缺少税额", "缺少价税合计"])


if __name__ == "__main__":
    unittest.main()
