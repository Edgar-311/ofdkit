import unittest
from unittest import mock

import ofdkit
from ofdkit.errors import OFDFormatError, OFDLimitError
from ofdkit.package import Package

from .ofdbuilder import OFDBuilder, Text, zip_parts


def _package(names):
    return Package(zip_parts({name: b"<a/>" for name in names}))


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.package = _package(["OFD.xml", "Doc_0/Document.xml", "Doc_0/Pages/Page_0/Content.xml", "Doc_0/Tpls/Tpl_0/Content.xml"])

    def tearDown(self):
        self.package.close()

    def test_relative_to_referencing_file(self):
        self.assertEqual(self.package.resolve("Doc_0/Document.xml", "Pages/Page_0/Content.xml"), "Doc_0/Pages/Page_0/Content.xml")

    def test_absolute_from_package_root(self):
        self.assertEqual(self.package.resolve("Doc_0/Document.xml", "/Doc_0/Pages/Page_0/Content.xml"), "Doc_0/Pages/Page_0/Content.xml")

    def test_root_relative_fallback(self):
        self.assertEqual(self.package.resolve("Doc_0/Document.xml", "Doc_0/Pages/Page_0/Content.xml"), "Doc_0/Pages/Page_0/Content.xml")

    def test_case_insensitive_fallback(self):
        self.assertEqual(self.package.resolve("Doc_0/Document.xml", "TPLS/tpl_0/content.xml"), "Doc_0/Tpls/Tpl_0/Content.xml")

    def test_backslashes_and_dot_segments(self):
        self.assertEqual(self.package.resolve("Doc_0/Document.xml", r".\Pages\Page_0\Content.xml"), "Doc_0/Pages/Page_0/Content.xml")

    def test_cannot_escape_the_package(self):
        self.assertIsNone(self.package.resolve("Doc_0/Document.xml", "../../etc/passwd"))

    def test_missing_and_empty(self):
        self.assertIsNone(self.package.resolve("Doc_0/Document.xml", "Pages/Page_9/Content.xml"))
        self.assertIsNone(self.package.resolve("Doc_0/Document.xml", ""))
        self.assertIsNone(self.package.resolve("Doc_0/Document.xml", None))


class PackageTest(unittest.TestCase):
    def test_not_a_zip(self):
        with self.assertRaises(OFDFormatError):
            ofdkit.open(b"not a zip file")

    def test_zip_without_ofd_xml(self):
        with self.assertRaises(OFDFormatError):
            ofdkit.open(zip_parts({"readme.txt": b"hello"}))

    def test_part_size_limit(self):
        data = OFDBuilder().build([[Text("测试样例", 20, 30)]])
        with mock.patch("ofdkit.package.MAX_PART_SIZE", 10):
            with self.assertRaises(OFDLimitError):
                ofdkit.open(data)

    def test_entry_count_limit(self):
        with mock.patch("ofdkit.package.MAX_ENTRIES", 2):
            with self.assertRaises(OFDLimitError):
                _package(["a.xml", "b.xml", "c.xml"])

    def test_gbk_entry_names_without_utf8_flag(self):
        builder = OFDBuilder()
        parts = builder.parts([[Text("中文目录", 20, 30)]])
        parts = {name.replace("Doc_0/", "文档/"): data for name, data in parts.items()}
        parts["OFD.xml"] = parts["OFD.xml"].replace("Doc_0/".encode(), "文档/".encode())
        with ofdkit.open(zip_parts(parts, gbk_names=True)) as document:
            self.assertEqual(document.text(), "中文目录")


if __name__ == "__main__":
    unittest.main()
