import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from ofdkit import __version__
from ofdkit.cli import EXIT_ERROR, EXIT_NO_INVOICE, EXIT_OK, main

from .ofdbuilder import OFDBuilder, Text


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
        self.assertIn("Pages:", out)
        self.assertIn("2 (210 x 297 mm)", out)
        self.assertIn("Invoice:", out)

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
        self.assertIn("3 invoices", err)
        self.assertIn("sum 25.50", err)

        _, _, err = run("batch", str(folder), "-r", "-o", str(target))
        self.assertIn("4 invoices", err)

    def test_batch_without_files(self):
        code, _, err = run("batch", str(self.root / "missing"))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("no .ofd files", err)


if __name__ == "__main__":
    unittest.main()
