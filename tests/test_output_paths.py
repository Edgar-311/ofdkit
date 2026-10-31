"""A mistyped export path must never replace the document being read."""

import os
import tempfile
import unittest
from pathlib import Path

from ofdkit.cli import EXIT_ERROR

from .ofdbuilder import OFDBuilder, Text, zip_parts
from .test_cli import run


class OutputPathTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = OFDBuilder().build([[Text("普通测试文档", 20, 30)]])

    def test_text_and_structure_cannot_replace_the_input(self):
        for command in ("text", "describe"):
            with self.subTest(command=command):
                source = self.root / f"{command}.ofd"
                source.write_bytes(self.data)
                code, _, err = run(command, str(source), "-o", str(source))
                self.assertEqual(code, EXIT_ERROR)
                self.assertIn("输出", err)
                self.assertEqual(source.read_bytes(), self.data)

    def test_batch_cannot_replace_its_input_archive(self):
        source = self.root / "documents.zip"
        data = zip_parts({"plain.ofd": self.data})
        source.write_bytes(data)
        code, _, err = run("batch", str(source), "-o", str(source))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("输入文件", err)
        self.assertEqual(source.read_bytes(), data)

    def test_a_hard_link_is_the_same_input_even_with_another_extension(self):
        source = self.root / "plain.ofd"
        target = self.root / "output.txt"
        source.write_bytes(self.data)
        try:
            os.link(source, target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        code, _, err = run("text", str(source), "-o", str(target))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("输入文件", err)
        self.assertEqual(source.read_bytes(), self.data)

    def test_export_cannot_replace_another_ofd_document(self):
        source = self.root / "plain.ofd"
        target = self.root / "other.OFD"
        source.write_bytes(self.data)
        target.write_bytes(self.data)
        code, _, err = run("text", str(source), "-o", str(target))
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn(".ofd", err)
        self.assertEqual(target.read_bytes(), self.data)


if __name__ == "__main__":
    unittest.main()
