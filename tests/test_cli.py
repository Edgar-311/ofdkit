import contextlib
import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ofdkit import __version__
from ofdkit.cli import EXIT_ERROR, EXIT_NO_INVOICE, EXIT_OK, main

from .ofdbuilder import OFDBuilder, Text, zip_parts


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.plain = self.write("plain.ofd", OFDBuilder(title="说明").build([[Text("第一页", 20, 30)], [Text("第二页", 20, 30)]]))

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return str(path)

    def invoice_file(self, name, number, total):
        builder = OFDBuilder(custom_data={"发票号码": number, "价税合计": total, "销售方名称": "测试单位乙"})
        return self.write(name, builder.build([[Text("测试样例", 20, 30)]]))

    def test_version_flag(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(__version__, out.getvalue())

    def test_no_command_prints_help(self):
        code, out, _ = run()
        self.assertEqual(code, EXIT_OK)
        self.assertIn("invoice", out)

    def test_text(self):
        code, out, _ = run("text", self.plain)
        self.assertEqual((code, out), (EXIT_OK, "第一页\n\n第二页\n"))

    def test_text_markdown(self):
        code, out, _ = run("text", self.plain, "--markdown")
        self.assertEqual((code, out), (EXIT_OK, "## 第 1 页\n\n第一页\n\n## 第 2 页\n\n第二页\n"))

    def test_text_to_file(self):
        target = self.root / "out.txt"
        code, out, _ = run("text", self.plain, "-o", str(target))
        self.assertEqual((code, out), (EXIT_OK, ""))
        self.assertEqual(target.read_text(encoding="utf-8"), "第一页\n\n第二页\n")

    def test_info_json(self):
        code, out, _ = run("info", self.plain, "--json")
        data = json.loads(out)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(len(data["pages"]), 2)
        self.assertEqual(data["info"]["title"], "说明")
        self.assertFalse(data["is_invoice"])

    def test_info_text(self):
        code, out, _ = run("info", self.plain)
        self.assertEqual(code, EXIT_OK)
        self.assertIn("页数      2（210 x 297 mm）", out)
        self.assertIn("是否发票  否", out)

    def test_invoice_json(self):
        path = self.invoice_file("a.ofd", "00000001", "¥10.00")
        code, out, _ = run("invoice", path)
        data = json.loads(out)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual((data["invoice_number"], data["total_amount"]), ("00000001", "10.00"))
        self.assertNotIn("raw", data)
        self.assertIn("raw", json.loads(run("invoice", path, "--raw")[1]))

    def test_invoice_on_plain_file(self):
        code, out, err = run("invoice", self.plain)
        self.assertEqual((code, out), (EXIT_NO_INVOICE, ""))
        self.assertIn("no invoice data", err)

    def test_errors_exit_with_code_2(self):
        self.assertEqual(run("text", str(self.root / "missing.ofd"))[0], EXIT_ERROR)
        broken = self.write("broken.ofd", b"not an ofd file")
        code, _, err = run("invoice", broken)
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("not an OFD file", err)

    def test_batch_csv(self):
        folder = self.root / "invoices"
        folder.mkdir()
        (folder / "sub").mkdir()
        for name, number, total in (("1.ofd", "00000001", "10.00"), ("2.OFD", "00000002", "5.50"), ("3.ofd", "00000001", "10.00")):
            (folder / name).write_bytes(Path(self.invoice_file(name, number, total)).read_bytes())
        (folder / "sub" / "4.ofd").write_bytes(Path(self.invoice_file("4.ofd", "00000004", "1.00")).read_bytes())
        (folder / "plain.ofd").write_bytes(Path(self.plain).read_bytes())
        (folder / "notes.txt").write_text("ignored", encoding="utf-8")
        target = self.root / "out.csv"

        code, _, err = run("batch", str(folder), "-o", str(target))
        self.assertEqual(code, EXIT_OK)
        raw = target.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "CSV should start with a BOM for Excel")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        self.assertEqual([Path(row["file"]).name for row in rows], ["1.ofd", "2.OFD", "3.ofd", "plain.ofd"])
        self.assertEqual(rows[0]["seller_name"], "测试单位乙")
        self.assertIn("duplicate invoice number", rows[0]["warnings"])
        self.assertEqual(rows[1]["warnings"], "")
        self.assertEqual(rows[3]["error"], "no invoice data")
        self.assertIn("共 4 个文件：3 张发票，1 个不是发票。", err)
        self.assertIn("价税合计 25.50 元", err)
        self.assertNotIn("税额 0.00", err, "sums of fields no invoice has are left out")
        self.assertIn("重复的只算一次的话，价税合计 15.50 元", err)

        _, _, err = run("batch", str(folder), "-r", "-o", str(target))
        self.assertIn("4 张发票", err)

    def test_batch_to_excel(self):
        target = self.root / "汇总.xlsx"
        code, out, err = run("batch", self.invoice_file("a.ofd", "00000001", "1.00"), self.plain, "-o", str(target))
        self.assertEqual((code, out), (EXIT_OK, ""))
        self.assertIn("已保存到", err)
        with zipfile.ZipFile(target) as archive:
            self.assertIn("xl/workbook.xml", archive.namelist())

    def test_batch_lists_unreadable_files(self):
        broken = self.write("broken.ofd", b"not an ofd file")
        code, _, err = run("batch", broken, "-o", str(self.root / "out.csv"))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("1 个读不出来", err)
        self.assertIn("broken.ofd：读不出来：不是 OFD 文件", err)

    def test_batch_reads_zip_archives(self):
        archive = self.root / "下载.zip"
        archive.write_bytes(zip_parts({"1.ofd": Path(self.invoice_file("1.ofd", "00000001", "1.00")).read_bytes()}))
        code, out, _ = run("batch", str(archive))
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([row["file"] for row in rows], [str(archive / "1.ofd")])

    def test_batch_without_files(self):
        code, _, err = run("batch", str(self.root / "missing"))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("找不到", err)
        self.assertIn("没有找到 .ofd 文件", err)


class ShowTest(unittest.TestCase):
    """``ofdkit show`` and its shortcut ``ofdkit PATH``."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return str(path)

    def invoice(self, name, number="00000001", total="106.00"):
        data = {"发票号码": number, "价税合计": total, "合计金额": "100.00", "合计税额": "6.00", "销售方名称": "测试单位乙"}
        return self.write(name, OFDBuilder(custom_data=data).build([[Text("测试样例", 20, 30)]]))

    def test_one_invoice(self):
        code, out, _ = run(self.invoice("a.ofd"))
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(out.splitlines()[0], "发票")
        self.assertIn("发票号码  00000001", out)
        self.assertIn("销售方    测试单位乙", out)
        self.assertIn("价税合计  106.00", out)
        self.assertEqual(run("show", self.invoice("b.ofd"))[1], out)

    def test_line_items_and_problems(self):
        from .test_invoice import DIGITAL_INVOICE_TAG, _values_page

        path = self.write("items.ofd", OFDBuilder().build([_values_page()], custom_tag=DIGITAL_INVOICE_TAG))
        out = run(path)[1]
        self.assertIn("明细      *测试*服务项目  100.00  6%", out)
        self.assertIn("购买方    测试单位甲\n          税号 TESTBUYER0001", out)

    def test_plain_document_shows_its_text(self):
        path = self.write("plain.ofd", OFDBuilder().build([[Text("普通文档", 20, 30)]]))
        self.assertEqual(run(path), (EXIT_OK, "普通文档\n", ""))

    def test_document_without_text(self):
        code, out, err = run(self.write("scan.ofd", OFDBuilder().build([[]])))
        self.assertEqual((code, out), (EXIT_OK, ""))
        self.assertIn("扫描件", err)

    def test_folder(self):
        self.invoice("1.ofd", "00000001", "106.00")
        self.invoice("2.ofd", "00000001", "106.00")
        self.write("3.ofd", b"broken")
        code, out, _ = run(str(self.root))
        self.assertEqual(code, EXIT_OK)
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["序号", "开票日期", "发票号码", "销售方", "价税合计", "提醒", "文件"])
        self.assertEqual(lines[1].split()[:5], ["1", "00000001", "测试单位乙", "106.00", "发票号码重复"])
        self.assertIn("读不出来", lines[3])
        self.assertIn("共 3 个文件：2 张发票，1 个读不出来。", out)
        self.assertIn("价税合计 212.00 元（金额 200.00，税额 12.00）。", out)
        self.assertIn("重复的只算一次的话，价税合计 106.00 元", out)
        self.assertIn(f"ofdkit batch {self.root} -o 发票汇总.xlsx", out)

    def test_missing_file(self):
        code, out, err = run(str(self.root / "missing.ofd"))
        self.assertEqual((code, out), (EXIT_ERROR, ""))
        self.assertIn("找不到", err)

    def test_empty_folder(self):
        code, _, err = run("show", str(self.root))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("没有找到 .ofd 文件。要连子文件夹一起找，请加 -r。", err)

    def test_text_hint_for_scans(self):
        code, out, err = run("text", self.write("scan.ofd", OFDBuilder().build([[]])))
        self.assertEqual((code, out), (EXIT_OK, "\n"))
        self.assertIn("扫描件", err)


if __name__ == "__main__":
    unittest.main()
