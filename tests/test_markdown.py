import importlib.util
import io
import unittest

import ofdkit
from ofdkit.markdown import document_markdown, escape

from .ofdbuilder import OFDBuilder, Text
from .test_invoice import DIGITAL_INVOICE_TAG, _values_page

HAS_MARKITDOWN = importlib.util.find_spec("markitdown") is not None


class MarkdownTest(unittest.TestCase):
    def test_single_page_is_plain_text(self):
        with ofdkit.open(OFDBuilder().build([[Text("正文", 20, 30)]])) as document:
            self.assertEqual(document_markdown(document), "正文\n")

    def test_pages_get_headings(self):
        with ofdkit.open(OFDBuilder().build([[Text("一", 20, 30)], [Text("二", 20, 30)]])) as document:
            self.assertEqual(document_markdown(document), "## 第 1 页\n\n一\n\n## 第 2 页\n\n二\n")

    def test_invoice_table_and_items(self):
        data = OFDBuilder().build([_values_page()], custom_tag=DIGITAL_INVOICE_TAG)
        with ofdkit.open(data) as document:
            markdown = document_markdown(document)
        self.assertTrue(markdown.startswith("## 发票信息\n"))
        self.assertIn("| 发票号码 | 00000000000000000001 |", markdown)
        self.assertIn("| 价税合计 | 106.00 |", markdown)
        self.assertIn("| 项目名称 | 金额 | 税率 | 税额 |", markdown)
        self.assertIn("| \\*测试\\*服务项目 | 100.00 | 6% | 6.00 |", markdown)
        self.assertIn("## 原文", markdown)

    def test_escape(self):
        self.assertEqual(escape("*a*_b_`c`\\"), "\\*a\\*\\_b\\_\\`c\\`\\\\")
        self.assertEqual(escape("# 标题\n > 引用\n文中#号"), "\\# 标题\n \\> 引用\n文中#号")


@unittest.skipUnless(HAS_MARKITDOWN, "markitdown is not installed")
class MarkItDownPluginTest(unittest.TestCase):
    def setUp(self):
        from markitdown import MarkItDown

        from ofdkit import markitdown_plugin

        self.plugin = markitdown_plugin
        self.converter = MarkItDown(enable_plugins=False)
        markitdown_plugin.register_converters(self.converter)
        self.data = OFDBuilder(title="说明").build([[Text("插件测试", 20, 30)]])

    def test_plugin_interface(self):
        self.assertEqual(self.plugin.__plugin_interface_version__, 1)

    def test_convert_by_extension(self):
        from markitdown import StreamInfo

        result = self.converter.convert_stream(io.BytesIO(self.data), stream_info=StreamInfo(extension=".ofd"))
        self.assertEqual(result.markdown, "插件测试\n")
        self.assertEqual(result.title, "说明")

    def test_accepts_sniffs_content_and_restores_position(self):
        from markitdown import StreamInfo

        stream = io.BytesIO(b"xx" + self.data)
        stream.seek(2)
        self.assertTrue(self.plugin.OfdConverter().accepts(stream, StreamInfo()))
        self.assertEqual(stream.tell(), 2)
        self.assertFalse(self.plugin.OfdConverter().accepts(io.BytesIO(b"PK\x03\x04broken"), StreamInfo()))
        self.assertFalse(self.plugin.OfdConverter().accepts(io.BytesIO(b"plain text"), StreamInfo(extension=".txt")))

    def test_entry_point_is_declared_when_installed(self):
        from importlib.metadata import entry_points

        names = {entry_point.value for entry_point in entry_points(group="markitdown.plugin")}
        if "ofdkit.markitdown_plugin" not in names:
            self.skipTest("ofdkit is not installed with its entry points")
        self.assertIn("ofdkit.markitdown_plugin", names)


if __name__ == "__main__":
    unittest.main()
