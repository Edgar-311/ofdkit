"""Renaming invoice files after their contents: preview, apply, undo."""

import contextlib
import csv
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ofdkit import rename
from ofdkit.cli import EXIT_ERROR, EXIT_OK, main
from ofdkit.invoice import Invoice, LineItem, Party

from .ofdbuilder import OFDBuilder, Text, zip_parts


def invoice_ofd(number="00000001", seller="测试单位乙", total="106.00", date="2026年01月02日"):
    data = {"发票号码": number, "开票日期": date, "价税合计": total}
    if seller:
        data["销售方名称"] = seller
    return OFDBuilder(custom_data=data).build([[Text("测试样例", 20, 30)]])


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def names(self):
        return sorted(path.name for path in self.root.iterdir())

    def test_plan_changes_nothing(self):
        self.write("dzfp_1.ofd", invoice_ofd())
        (plan,) = rename.plan([self.root])
        self.assertEqual(plan.target, self.root / "2026-01-02_测试单位乙_106.00_00000001.ofd")
        self.assertEqual(self.names(), ["dzfp_1.ofd"])

    def test_apply_and_undo(self):
        self.write("dzfp_1.ofd", invoice_ofd())
        self.write("dzfp_1.PDF", b"pdf copy")
        self.write("dzfp_1.xml", b"<xml/>")
        self.write("dzfp_1.txt", b"not a copy of the invoice")
        outcome = rename.apply(rename.plan([self.root]))
        new = "2026-01-02_测试单位乙_106.00_00000001"
        self.assertEqual(len(outcome.done), 3)
        self.assertEqual(outcome.failed, [])
        self.assertIsNotNone(outcome.log)
        self.assertTrue(outcome.log.name.startswith("改名记录_"))
        self.assertEqual(self.names(), sorted([f"{new}.ofd", f"{new}.PDF", f"{new}.xml", "dzfp_1.txt", outcome.log.name]))
        with open(outcome.log, encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[0], ["原来的文件", "新的文件"])
        self.assertTrue(Path(rows[1][0]).is_absolute())

        restored = rename.undo(outcome.log)
        self.assertEqual(len(restored.done), 3)
        self.assertEqual(self.names(), sorted(["dzfp_1.ofd", "dzfp_1.PDF", "dzfp_1.xml", "dzfp_1.txt", outcome.log.name]))

    def test_without_companions(self):
        self.write("a.ofd", invoice_ofd())
        self.write("a.pdf", b"pdf copy")
        (plan,) = rename.plan([self.root], companions=False)
        self.assertEqual(plan.companions, [])

    def test_name_conflicts_get_a_number_and_a_second_run_changes_nothing(self):
        self.write("a.ofd", invoice_ofd())
        self.write("b.ofd", invoice_ofd())  # the same invoice twice
        self.write("2026-01-02_测试单位乙_5.00_00000002.ofd", b"some other file already has this name")
        self.write("c.ofd", invoice_ofd(number="00000002", total="5.00"))
        plans = {plan.source.name: plan for plan in rename.plan([self.root])}
        self.assertEqual(plans["a.ofd"].target.name, "2026-01-02_测试单位乙_106.00_00000001.ofd")
        self.assertEqual(plans["b.ofd"].target.name, "2026-01-02_测试单位乙_106.00_00000001 (2).ofd")
        self.assertTrue(plans["b.ofd"].duplicate)
        self.assertEqual(plans["c.ofd"].target.name, "2026-01-02_测试单位乙_5.00_00000002 (2).ofd")

        rename.apply(list(plans.values()))
        again = rename.plan([self.root])
        self.assertTrue(all(plan.target is None for plan in again), [(p.source.name, p.target) for p in again])
        self.assertIn("已经是这个名字", {plan.skipped for plan in again})

    def test_files_that_are_not_renamed(self):
        self.write("plain.ofd", OFDBuilder().build([[Text("普通文档", 20, 30)]]))
        self.write("broken.ofd", b"broken")
        archive = self.write("archive.zip", zip_parts({"a.ofd": invoice_ofd()}))
        reasons = {plan.source.name: plan.skipped for plan in rename.plan([self.root, archive])}
        self.assertEqual(reasons["plain.ofd"], "不是发票（没有发票数据）")
        self.assertTrue(reasons["broken.ofd"].startswith("读不出来"))
        self.assertEqual(reasons["archive.zip"], "压缩包里的文件不能改名")

    def test_apply_never_overwrites(self):
        self.write("a.ofd", invoice_ofd())
        plans = rename.plan([self.root])
        plans[0].target.write_bytes(b"appeared after the preview")
        outcome = rename.apply(plans)
        self.assertEqual(outcome.done, [])
        self.assertEqual(outcome.failed[0][2], "新名字已经有文件在用")
        self.assertIsNone(outcome.log)
        self.assertEqual(plans[0].target.read_bytes(), b"appeared after the preview")
        self.assertTrue((self.root / "a.ofd").exists())

    def test_undo_rejects_other_files(self):
        log = self.write("other.csv", b"a,b\n")
        with self.assertRaises(ValueError):
            rename.undo(log)

    def test_missing_path(self):
        with self.assertRaises(FileNotFoundError):
            rename.plan([self.root / "missing"])


class RecoveryTest(unittest.TestCase):
    """The log is written before anything is renamed, and one invoice's files move together."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "a.ofd").write_bytes(invoice_ofd("00000001"))
        (self.root / "a.pdf").write_bytes(b"pdf copy of a")
        (self.root / "b.ofd").write_bytes(invoice_ofd("00000002"))
        self.original = self.names()

    def names(self):
        return sorted(path.name for path in self.root.iterdir() if not path.name.startswith("改名记录"))

    def logs(self):
        return sorted(self.root.glob("改名记录_*.csv"))

    def test_no_log_means_no_renames(self):
        # Regression: files used to be renamed first, and the log written at the end.
        real_open = open

        def deny_log(path, *args, **kwargs):
            if "改名记录" in str(path):
                raise PermissionError(13, "Permission denied", str(path))
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", deny_log), self.assertRaises(rename.LogError):
            rename.apply(rename.plan([self.root]))
        self.assertEqual(self.names(), self.original)
        with mock.patch("builtins.open", deny_log):
            code, _, err = run("rename", str(self.root), "--apply")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("没有改任何文件", err)
        self.assertEqual(self.names(), self.original)

    def test_log_folder_that_does_not_exist(self):
        with self.assertRaises(rename.LogError):
            rename.apply(rename.plan([self.root]), log_folder=self.root / "missing")
        self.assertEqual(self.names(), self.original)

    def test_every_rename_is_in_the_log_before_it_happens(self):
        seen = []
        real_rename = os.rename

        def check_then_rename(old, new):
            (log,) = self.logs()
            seen.append(str(Path(new).resolve()) in log.read_text(encoding="utf-8-sig"))
            real_rename(old, new)

        with mock.patch("ofdkit.rename.os.rename", check_then_rename):
            outcome = rename.apply(rename.plan([self.root]))
        self.assertEqual(seen, [True, True, True])
        self.assertEqual(len(outcome.done), 3)

    def test_log_that_stops_being_writable_stops_renaming(self):
        real_write = rename._write_line
        calls = []

        def fail_third(*args):
            calls.append(args)
            if len(calls) == 3:  # a.ofd and a.pdf are logged and renamed; b.ofd is not
                raise OSError(28, "No space left on device")
            real_write(*args)

        with mock.patch.object(rename, "_write_line", fail_third):
            outcome = rename.apply(rename.plan([self.root]))
        self.assertEqual([old.name for old, _ in outcome.done], ["a.ofd", "a.pdf"])
        self.assertIn("改名记录写不进去", outcome.failed[0][2])
        self.assertTrue((self.root / "b.ofd").exists())
        rename.undo(outcome.log)
        self.assertEqual(self.names(), self.original)

    def test_a_name_the_log_cannot_hold_stops_renaming(self):
        with mock.patch.object(rename, "_write_line", side_effect=UnicodeEncodeError("utf-8", "\udcff", 0, 1, "surrogate")):
            outcome = rename.apply(rename.plan([self.root]))
        self.assertEqual(outcome.done, [])
        self.assertIn("改名记录写不进去", outcome.failed[0][2])
        self.assertEqual(self.names(), self.original)

    def test_a_copy_that_fails_takes_its_invoice_back(self):
        real_rename = os.rename

        def pdf_is_open(old, new):
            if str(old).endswith("a.pdf"):
                raise PermissionError(13, "in use", str(old))
            real_rename(old, new)

        with mock.patch("ofdkit.rename.os.rename", pdf_is_open):
            outcome = rename.apply(rename.plan([self.root]))
        self.assertEqual([old.name for old, _ in outcome.rolled_back], ["a.ofd"])
        self.assertEqual([(old.name, reason) for old, _, reason in outcome.failed], [("a.pdf", "文件可能正在被别的软件打开")])
        self.assertEqual([old.name for old, _ in outcome.done], ["b.ofd"])
        self.assertTrue((self.root / "a.ofd").exists() and (self.root / "a.pdf").exists(), "a keeps matching names")

        restored = rename.undo(outcome.log)
        self.assertEqual([new.name for _, new in restored.done], ["b.ofd"])
        self.assertEqual(sorted(old.name for _, old in restored.unchanged), ["a.ofd", "a.pdf"])
        self.assertEqual(restored.failed, [])
        self.assertEqual(self.names(), self.original)

    def test_failed_roll_back_stays_in_the_log(self):
        real_rename = os.rename

        def stuck(old, new):
            if str(old).endswith("a.pdf") or str(new).endswith("a.ofd"):
                raise PermissionError(13, "in use", str(old))
            real_rename(old, new)

        with mock.patch("ofdkit.rename.os.rename", stuck):
            outcome = rename.apply(rename.plan([self.root]))
        self.assertEqual(len(outcome.failed), 2)  # a.pdf, then a.ofd could not go back
        self.assertIsNotNone(outcome.log)
        self.assertIn("a.ofd", outcome.log.read_text(encoding="utf-8-sig"))
        rename.undo(outcome.log)
        self.assertEqual(self.names(), self.original)

    def test_nothing_renamed_leaves_no_log(self):
        with mock.patch("ofdkit.rename.os.rename", side_effect=PermissionError(13, "in use")):
            outcome = rename.apply(rename.plan([self.root]))
        self.assertEqual(outcome.done, [])
        self.assertIsNone(outcome.log)
        self.assertEqual(self.logs(), [])

    def test_undo_twice_is_harmless(self):
        outcome = rename.apply(rename.plan([self.root]))
        rename.undo(outcome.log)
        again = rename.undo(outcome.log)
        self.assertEqual((again.done, again.failed), ([], []))
        self.assertEqual(len(again.unchanged), 3)
        code, out, _ = run("rename", "--undo", str(outcome.log))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("3 个文件本来就是原来的名字", out)


class NewNameTest(unittest.TestCase):
    invoice = Invoice(
        invoice_number="00000001",
        issue_date="2026-01-02",
        seller=Party(name='测试/单位:乙*'),
        total_amount="106.00",
        items=[LineItem(name="*测试*服务")],
    )

    def test_default_pattern_and_unsafe_characters(self):
        self.assertEqual(rename.new_name(self.invoice, Path("a.ofd")), "2026-01-02_测试单位乙_106.00_00000001")

    def test_fields_by_english_name_and_items(self):
        self.assertEqual(rename.new_name(self.invoice, Path("a.ofd"), "{date} {item} {name}"), "2026-01-02 测试-服务 a")

    def test_empty_fields_leave_no_doubled_separators(self):
        self.assertEqual(rename.new_name(self.invoice, Path("a.ofd"), "{开票日期}_{购买方}_{价税合计}"), "2026-01-02_106.00")
        self.assertEqual(rename.new_name(Invoice(), Path("a.ofd"), "{购买方}_{税额}"), "")

    def test_bad_patterns(self):
        for pattern in ("no fields", "{日期}", "{开票日期}/{销售方}"):
            with self.assertRaises(ValueError):
                rename.check_pattern(pattern)

    def test_reserved_and_long_names(self):
        self.assertEqual(rename.new_name(Invoice(seller=Party(name="CON")), Path("a.ofd"), "{销售方}"), "_CON")
        long_name = rename.new_name(Invoice(seller=Party(name="甲" * 300)), Path("a.ofd"), "{销售方}")
        self.assertEqual(len(long_name), rename.MAX_NAME_LENGTH)


class RenameCliTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "dzfp_1.ofd").write_bytes(invoice_ofd())
        (self.root / "plain.ofd").write_bytes(OFDBuilder().build([[Text("普通文档", 20, 30)]]))

    def tearDown(self):
        self.directory.cleanup()

    def test_preview_then_apply_then_undo(self):
        code, out, _ = run("rename", str(self.root))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("预览（还没有改名）", out)
        self.assertIn("→ 2026-01-02_测试单位乙_106.00_00000001.ofd", out)
        self.assertIn("plain.ofd：不是发票", out)
        self.assertIn(f"ofdkit rename {self.root} --apply", out)
        self.assertTrue((self.root / "dzfp_1.ofd").exists(), "a preview renames nothing")

        code, out, _ = run("rename", str(self.root), "--apply")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("已改名 1 个文件", out)
        self.assertTrue((self.root / "2026-01-02_测试单位乙_106.00_00000001.ofd").exists())
        (log,) = self.root.glob("改名记录_*.csv")
        self.assertIn("ofdkit rename --undo", out)

        code, out, _ = run("rename", "--undo", str(log))
        self.assertEqual(code, EXIT_OK)
        self.assertIn("已改回 1 个文件", out)
        self.assertTrue((self.root / "dzfp_1.ofd").exists())

    def test_custom_pattern_is_repeated_in_the_apply_hint(self):
        code, out, _ = run("rename", str(self.root), "--pattern", "{开票日期} {销售方}")
        self.assertEqual(code, EXIT_OK)
        self.assertIn('--pattern "{开票日期} {销售方}" --apply', out)

    def test_errors(self):
        self.assertEqual(run("rename")[0], EXIT_ERROR)
        self.assertEqual(run("rename", str(self.root), "--undo", "x.csv")[0], EXIT_ERROR)
        code, _, err = run("rename", str(self.root), "--pattern", "{日期}")
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("不认识的字段：日期", err)


if __name__ == "__main__":
    unittest.main()
