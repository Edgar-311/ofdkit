"""Reading stays inside one folder even when links inside it point elsewhere (MCP --root)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ofdkit import batch
from ofdkit._guard import OutsideRootError, PathGuard

from .ofdbuilder import OFDBuilder, Text, zip_parts


def invoice(number):
    return OFDBuilder(custom_data={"发票号码": number, "价税合计": "1.00"}).build([[Text("测试样例", 20, 30)]])


def link_file(target, link):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        raise unittest.SkipTest(f"cannot create a file link here: {exc}") from exc


def link_folder(target, link, junction=False, test=None):
    """A symbolic link to a folder, or on Windows with ``junction`` a directory junction.

    A junction is removed by ``test``'s cleanup before the temporary folders are, so that
    deleting them never reaches through it.
    """
    if junction:
        if sys.platform != "win32":
            raise unittest.SkipTest("directory junctions exist only on Windows")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
        test.addCleanup(remove_junction, link)
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        raise unittest.SkipTest(f"cannot create a folder link here: {exc}") from exc


def remove_junction(link):
    """Remove the junction itself (os.rmdir does not follow it); fine if it is gone already."""
    try:
        os.rmdir(link)
    except FileNotFoundError:
        pass


class GuardTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(os.path.realpath(directory.name))
        self.allowed, self.outside = base / "allowed", base / "outside"
        self.allowed.mkdir()
        self.outside.mkdir()
        (self.allowed / "inside.ofd").write_bytes(invoice("00000001"))
        (self.outside / "secret.ofd").write_bytes(invoice("99999999"))
        (self.outside / "secret.zip").write_bytes(zip_parts({"a.ofd": invoice("99999998")}))
        self.guard = PathGuard(self.allowed)

    def numbers(self, recursive):
        files, _ = batch.find_ofd_files([self.allowed], recursive, guard=self.guard)
        results = batch.read_invoice_files(files, guard=self.guard)
        return sorted(r.invoice.invoice_number for r in results if r.invoice)

    def test_file_link_to_outside_is_skipped(self):
        link_file(self.outside / "secret.ofd", self.allowed / "link.ofd")
        link_file(self.outside / "secret.zip", self.allowed / "link.zip")
        for recursive in (False, True):
            self.guard.refused.clear()
            self.assertEqual(self.numbers(recursive), ["00000001"])
            self.assertEqual(sorted(Path(p).name for p in self.guard.refused), ["link.ofd", "link.zip"])

    def test_folder_link_to_outside_is_not_entered(self):
        link_folder(self.outside, self.allowed / "linked")
        self.assertEqual(self.numbers(recursive=True), ["00000001"])
        self.assertEqual([Path(p).name for p in self.guard.refused], ["linked"])

    def test_directory_junction_to_outside_is_not_entered(self):
        link_folder(self.outside, self.allowed / "junction", junction=True, test=self)
        self.assertEqual(self.numbers(recursive=True), ["00000001"])
        self.assertEqual([Path(p).name for p in self.guard.refused], ["junction"])

    def test_links_that_stay_inside_are_followed(self):
        (self.allowed / "sub").mkdir()
        (self.allowed / "sub" / "deep.ofd").write_bytes(invoice("00000002"))
        link_folder(self.allowed / "sub", self.allowed / "alias")
        link_folder(self.allowed, self.allowed / "sub" / "loop")  # a loop must end
        link_file(self.allowed / "inside.ofd", self.allowed / "again.ofd")
        numbers = self.numbers(recursive=True)
        self.assertEqual(set(numbers), {"00000001", "00000002"})
        self.assertEqual(self.guard.refused, [])

    def test_reading_a_file_that_leads_outside_fails(self):
        link_file(self.outside / "secret.ofd", self.allowed / "link.ofd")
        (result,) = batch.read_invoice_files([self.allowed / "link.ofd"], guard=self.guard)
        self.assertIsNone(result.invoice)
        self.assertIn("outside the allowed folder", result.error)
        with self.assertRaises(OutsideRootError):
            self.guard.open(self.allowed / "link.ofd")

    def test_open_uses_the_real_location_and_catches_a_swap(self):
        link_file(self.allowed / "inside.ofd", self.allowed / "again.ofd")
        with self.guard.open(self.allowed / "again.ofd") as stream:
            self.assertEqual(Path(stream.name), self.allowed / "inside.ofd")
        # The file is replaced between the check and the open: the second look fails.
        with mock.patch.object(PathGuard, "inside", side_effect=[False]), self.assertRaises(OutsideRootError):
            self.guard.open(self.allowed / "inside.ofd")

    def test_without_a_guard_nothing_changes(self):
        link_file(self.outside / "secret.ofd", self.allowed / "link.ofd")
        files, _ = batch.find_ofd_files([self.allowed])
        self.assertEqual(sorted(p.name for p in files), ["inside.ofd", "link.ofd"])


if __name__ == "__main__":
    unittest.main()
