import json
import unittest

from ofdkit.cli import main
from ofdkit.describe import describe, mask

from .ofdbuilder import OFDBuilder, Text, zip_parts
from .test_cli import run

SECRETS = ["测试单位甲", "TESTID0001", "00000001", "123.45", "说明文档"]


def _file(**kwargs):
    builder = OFDBuilder(title="说明文档", custom_data={"编号": "00000001"})
    parts = builder.parts([[Text("测试单位甲", 20, 30, id=11), Text("TESTID0001", 20, 40), Text("123.45", 20, 50)]], **kwargs)
    parts["Doc_0/Res/seal.png"] = b"\x89PNG not really an image"
    return parts


class MaskTest(unittest.TestCase):
    def test_mask(self):
        self.assertEqual(mask("测试 Ab9，¥1.5"), "字字 Xx0，¥0.0")


class DescribeTest(unittest.TestCase):
    def test_no_content_leaks(self):
        raw = json.dumps(describe(zip_parts(_file())), ensure_ascii=False)
        for secret in SECRETS:
            self.assertNotIn(secret, raw)

    def test_structure_and_positions_are_kept(self):
        data = describe(zip_parts(_file()))
        names = [entry["name"] for entry in data["entries"]]
        self.assertIn("Doc_0/Res/seal.png", names)
        self.assertNotIn("Doc_0/Res/seal.png", data["xml"])
        page = data["xml"]["Doc_0/Pages/Page_0/Content.xml"]
        self.assertEqual(page["encoding"], "UTF-8")
        self.assertFalse(page["needed_repair"])
        layer = page["root"]["children"][0]["children"][0]
        first = layer["children"][0]
        self.assertEqual(first["tag"], "TextObject")
        self.assertEqual(first["attrs"]["ID"], "11")
        self.assertEqual(first["attrs"]["Boundary"], "20 26.0 20.0 5.0")
        self.assertEqual(first["children"][0]["text"], "字字字字字")
        fonts = data["xml"]["Doc_0/PublicRes.xml"]["root"]["children"][0]["children"][0]["attrs"]
        self.assertEqual(fonts["FontName"], "宋体")
        doc_root = data["xml"]["OFD.xml"]["root"]["children"][0]["children"][1]
        self.assertEqual((doc_root["tag"], doc_root["text"]), ("DocRoot", "Doc_0/Document.xml"))

    def test_namespace_only_where_it_changes(self):
        root = describe(zip_parts(_file()))["xml"]["OFD.xml"]["root"]
        self.assertEqual(root["ns"], "http://www.ofdspec.org/2016")
        self.assertNotIn("ns", root["children"][0])

    def test_broken_xml_and_legacy_names_are_reported(self):
        parts = _file(custom_tag='<:eInvoice xmlns:=""><InvoiceNo>00000001</InvoiceNo></:eInvoice>')
        parts = {name.replace("Doc_0/", "文档/"): data for name, data in parts.items()}
        parts["OFD.xml"] = parts["OFD.xml"].replace(b"Doc_0/", "文档/".encode())
        data = describe(zip_parts(parts, gbk_names=True))
        entry = next(entry for entry in data["entries"] if entry["name"].endswith("Document.xml"))
        self.assertEqual(entry["name"], "字字/Document.xml")
        self.assertTrue(entry["name_decoded_from_legacy_encoding"])
        self.assertFalse(entry["utf8_name_flag"])
        tag = data["xml"]["字字/Tags/CustomTag.xml"]
        self.assertTrue(tag["needed_repair"])
        self.assertNotIn("00000001", json.dumps(data, ensure_ascii=False))

    def test_cli_writes_a_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "a.ofd"
            source.write_bytes(zip_parts(_file()))
            target = Path(directory) / "a.json"
            code, out, err = run("describe", str(source), "-o", str(target))
            self.assertEqual((code, out), (0, ""))
            self.assertIn("分享之前请再检查", err)
            self.assertIn("entries", json.loads(target.read_text(encoding="utf-8")))
        self.assertIs(main, main)


if __name__ == "__main__":
    unittest.main()
