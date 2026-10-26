"""Reading many files: folders, ZIP archives, duplicates and totals."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ofdkit
from ofdkit import batch
from ofdkit.batch import (
    EMPTY_ARCHIVE,
    NO_INVOICE,
    InvoiceFile,
    find_ofd_files,
    item_names,
    problems,
    summary,
)
from ofdkit.invoice import Invoice, LineItem

from .ofdbuilder import OFDBuilder, Text, zip_parts


def invoice_ofd(number, total, code=None, seller="测试单位乙"):
    data = {"发票号码": number, "价税合计": total, "销售方名称": seller}
    if code:
        data["发票代码"] = code
    return OFDBuilder(custom_data=data).build([[Text("测试样例", 20, 30)]])


def plain_ofd():
    return OFDBuilder().build([[Text("普通文档", 20, 30)]])


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def archive(self, name, entries, gbk_names=False):
        path = self.root / name
        path.write_bytes(zip_parts(entries, gbk_names=gbk_names))
        return path

    def test_ofd_files_inside_an_archive_are_read(self):
        archive = self.archive(
            "下载.zip",
            {
                "b.ofd": invoice_ofd("00000002", "2.00"),
                "子目录/发票.OFD": invoice_ofd("00000001", "1.00"),
                "说明.txt": b"not an ofd",
                "a.ofd": plain_ofd(),
            },
        )
        results = ofdkit.read_invoices(archive)
        self.assertEqual(
            [result.file for result in results],
            [str(archive / "a.ofd"), str(archive / "b.ofd"), str(archive / "子目录" / "发票.OFD")],
        )
        self.assertEqual(results[0].error, NO_INVOICE)
        self.assertEqual([r.invoice.invoice_number for r in results[1:]], ["00000002", "00000001"])

    def test_gbk_names_in_an_archive(self):
        archive = self.archive("gbk.zip", {"发票一.ofd": invoice_ofd("00000003", "3.00")}, gbk_names=True)
        (result,) = ofdkit.read_invoices(archive)
        self.assertEqual(result.file, str(archive / "发票一.ofd"))

    def test_folders_include_archives_that_hold_ofd_files(self):
        self.archive("invoices.zip", {"1.ofd": invoice_ofd("00000001", "1.00")})
        self.archive("other.zip", {"readme.txt": b"nothing here"})
        (self.root / "2.ofd").write_bytes(invoice_ofd("00000002", "2.00"))
        files, missing = find_ofd_files([self.root])
        self.assertEqual([path.name for path in files], ["2.ofd", "invoices.zip"])
        self.assertEqual(missing, [])
        self.assertEqual(len(ofdkit.read_invoices(self.root)), 2)

    def test_archive_given_directly_without_ofd_files(self):
        archive = self.archive("other.zip", {"readme.txt": b"nothing here"})
        (result,) = ofdkit.read_invoices(archive)
        self.assertEqual((result.file, result.error), (str(archive), EMPTY_ARCHIVE))
        self.assertEqual(problems(result), ["压缩包里没有 OFD 文件"])

    def test_ofd_file_named_zip_is_read_as_ofd(self):
        path = self.root / "invoice.zip"
        path.write_bytes(invoice_ofd("00000009", "9.00"))
        (result,) = ofdkit.read_invoices(path)
        self.assertEqual((result.file, result.invoice.invoice_number), (str(path), "00000009"))

    def test_oversized_entries_are_skipped(self):
        archive = self.archive("big.zip", {"1.ofd": invoice_ofd("00000001", "1.00")})
        with mock.patch.object(batch, "MAX_ARCHIVE_MEMBER_SIZE", 10):
            (result,) = ofdkit.read_invoices(archive)
        self.assertIn("too large", result.error)

    def test_limit_stops_inside_an_archive(self):
        entries = {f"{n}.ofd": invoice_ofd(f"0000000{n}", "1.00") for n in range(5)}
        archive = self.archive("many.zip", entries)
        results = batch.read_invoice_files([archive], limit=3)
        self.assertEqual(len(results), 3)

    def test_missing_path(self):
        with self.assertRaises(FileNotFoundError):
            ofdkit.read_invoices([self.root / "missing"])


class DuplicateTest(unittest.TestCase):
    def read(self, *datas):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, data in enumerate(datas):
                path = Path(directory) / f"{index}.ofd"
                path.write_bytes(data)
                paths.append(path)
            return batch.read_invoice_files(paths)

    def test_same_number_is_a_duplicate(self):
        results = self.read(invoice_ofd("00000001", "10.00"), invoice_ofd("00000001", "10.00"), invoice_ofd("00000002", "5.00"))
        self.assertEqual([r.duplicate for r in results], [True, True, False])
        totals = summary(results)
        self.assertEqual((totals["duplicates"], totals["total_amount_sum"]), (1, "25.00"))
        self.assertEqual(totals["total_amount_sum_without_duplicates"], "15.00")
        self.assertIn("duplicate invoice number", batch.invoice_row(results[0])["warnings"])
        self.assertEqual(problems(results[0]), ["发票号码重复"])

    def test_older_invoices_need_the_same_code_too(self):
        results = self.read(
            invoice_ofd("00000001", "1.00", code="000000000001"), invoice_ofd("00000001", "1.00", code="000000000002")
        )
        self.assertEqual([r.duplicate for r in results], [False, False])
        self.assertEqual(summary(results)["duplicates"], 0)

    def test_summary_accepts_rows(self):
        results = self.read(invoice_ofd("00000001", "10.00"), plain_ofd())
        rows = [batch.invoice_row(result) for result in results]
        self.assertEqual(summary(rows), summary(results))
        self.assertEqual(summary(rows)["without_invoice_data"], 1)


class TextTest(unittest.TestCase):
    def test_item_names(self):
        invoice = Invoice(items=[LineItem(name="*甲*一"), LineItem(name="*甲*一"), LineItem(name="*乙*二"), LineItem()])
        self.assertEqual(item_names(invoice), "*甲*一；*乙*二")
        self.assertEqual(item_names(invoice, limit=1), "*甲*一等")
        self.assertEqual(item_names(Invoice()), "")

    def test_problems_in_chinese(self):
        invoice = Invoice(warnings=["amount_without_tax + tax_amount != total_amount (1.00 + 0.10 != 1.20)", "其他"])
        self.assertEqual(
            problems(InvoiceFile("a.ofd", invoice=invoice)), ["金额 + 税额 ≠ 价税合计（1.00 + 0.10 ≠ 1.20）", "其他"]
        )
        broken = InvoiceFile("b.ofd", error="not an OFD file (not a ZIP container): bad")
        self.assertTrue(problems(broken)[0].startswith("读不出来：不是 OFD 文件"))
        self.assertEqual(problems(InvoiceFile("c.ofd", error="missing part: x")), ["读不出来：missing part: x"])

    def test_read_invoices_accepts_paths_and_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a.ofd"
            path.write_bytes(invoice_ofd("00000001", "1.00"))
            self.assertEqual(len(ofdkit.read_invoices(str(path))), 1)
            self.assertEqual(len(ofdkit.read_invoices([path, path])), 2)


if __name__ == "__main__":
    unittest.main()
