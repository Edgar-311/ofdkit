import io
import unittest
import xml.etree.ElementTree as ET

import ofdkit
from ofdkit.document import _compose, _object_transform, _parse_deltas

from .ofdbuilder import OFD_NS, OFDBuilder, Text, zip_parts


class DocumentTest(unittest.TestCase):
    def test_opens_bytes_path_and_file_object(self):
        data = OFDBuilder().build([[Text("测试样例", 20, 30)]])
        with ofdkit.open(data) as document:
            self.assertEqual(document.text(), "测试样例")
        with ofdkit.open(io.BytesIO(data)) as document:
            self.assertEqual(len(document.pages), 1)

    def test_doc_info(self):
        builder = OFDBuilder(title="说明文档", custom_data={"项目": "测试"})
        with ofdkit.open(builder.build([[Text("正文", 20, 30)]])) as document:
            self.assertEqual(document.info.title, "说明文档")
            self.assertEqual(document.info.doc_id, "test")
            self.assertEqual(document.info.custom_data, {"项目": "测试"})

    def test_page_ids_sizes_and_lookup(self):
        builder = OFDBuilder(page_size=(100.0, 50.0))
        with ofdkit.open(builder.build([[Text("一", 10, 10)], [Text("二", 10, 10)]])) as document:
            self.assertEqual([page.id for page in document.pages], ["1", "2"])
            self.assertEqual((document.pages[0].width, document.pages[0].height), (100.0, 50.0))
            self.assertIs(document.page_by_id("2"), document.pages[1])
            self.assertIsNone(document.page_by_id("9"))
            self.assertEqual(document.text(), "一\n\n二")

    def test_reading_order_top_to_bottom_left_to_right(self):
        texts = [
            Text("第二行", 20, 36),
            Text("右", 120, 30),
            Text("左", 20, 30.4),  # slightly lower baseline, still the same line
            Text("第三行", 20, 42),
        ]
        with ofdkit.open(OFDBuilder().build([texts])) as document:
            self.assertEqual(document.text(), "左   右\n第二行\n第三行")

    def test_paragraph_gap_inserts_blank_line(self):
        texts = [Text("上段", 20, 30), Text("下段", 20, 60)]
        with ofdkit.open(OFDBuilder().build([texts])) as document:
            self.assertEqual(document.text(), "上段\n\n下段")

    def test_word_gap_from_delta_x(self):
        # "AB" spaced by DeltaX ends at 20 + 4 + 2 = 26mm; "CD" starts 3mm later.
        texts = [Text("AB", 20, 30, delta_x="4"), Text("CD", 29, 30)]
        with ofdkit.open(OFDBuilder().build([texts])) as document:
            self.assertEqual(document.text(), "AB CD")

    def test_duplicate_runs_are_dropped(self):
        texts = [Text("加粗", 20, 30), Text("加粗", 20.05, 30)]
        with ofdkit.open(OFDBuilder().build([texts])) as document:
            self.assertEqual(document.text(), "加粗")

    def test_template_text_is_included(self):
        builder = OFDBuilder()
        data = builder.build([[Text("内容", 40, 30)]], template=[Text("标签：", 20, 30)])
        with ofdkit.open(data) as document:
            self.assertEqual(document.text(), "标签：   内容")
            self.assertEqual([run.from_template for run in document.pages[0].runs], [True, False])

    def test_text_outside_the_page_is_not_shown(self):
        texts = [Text("可见", 20, 30, id=1), Text("页外", 20, 500, id=2)]
        with ofdkit.open(OFDBuilder().build([texts])) as document:
            self.assertEqual(document.text(), "可见")
            self.assertEqual(document.pages[0].object_text("2"), "页外")

    def test_absolute_paths_and_namespace_variants(self):
        for namespace in (OFD_NS, "http://www.ofdspec.org", None):
            with self.subTest(namespace=namespace):
                builder = OFDBuilder(namespace=namespace, absolute_paths=True)
                data = builder.build([[Text("正文", 20, 30)]], template=[Text("模板", 20, 25)])
                with ofdkit.open(data) as document:
                    self.assertEqual(document.text(), "模板\n正文")

    def test_missing_page_content_gives_warning(self):
        parts = OFDBuilder().parts([[Text("一", 20, 30)], [Text("二", 20, 30)]])
        del parts["Doc_0/Pages/Page_1/Content.xml"]
        with ofdkit.open(zip_parts(parts)) as document:
            self.assertEqual(len(document.pages), 2)
            self.assertEqual(document.text(), "一\n\n")
            self.assertTrue(any("page 2" in warning for warning in document.warnings))

    def test_unreadable_page_gives_warning_and_others_still_read(self):
        parts = OFDBuilder().parts([[Text("一", 20, 30)], [Text("二", 20, 30)]])
        parts["Doc_0/Pages/Page_0/Content.xml"] = b"<broken"
        with ofdkit.open(zip_parts(parts)) as document:
            self.assertEqual(document.text(), "\n\n二")
            self.assertTrue(any(warning.startswith("page 1:") for warning in document.warnings))

    def test_ctm_scales_text_object_space(self):
        page = (
            f'<ofd:Page xmlns:ofd="{OFD_NS}"><ofd:Content><ofd:Layer ID="2">'
            '<ofd:TextObject ID="3" Boundary="10 20 50 10" CTM="2 0 0 2 1 0" Font="1" Size="2">'
            '<ofd:TextCode X="3" Y="4">缩放</ofd:TextCode></ofd:TextObject>'
            "</ofd:Layer></ofd:Content></ofd:Page>"
        ).encode()
        parts = OFDBuilder().parts([[]])
        parts["Doc_0/Pages/Page_0/Content.xml"] = page
        with ofdkit.open(zip_parts(parts)) as document:
            (run,) = document.pages[0].runs
            self.assertEqual((run.x, run.y, run.size), (10 + 2 * 3 + 1, 20 + 2 * 4, 4.0))

    def test_text_inside_composite_objects_and_page_blocks(self):
        resources = (
            f'<ofd:Res xmlns:ofd="{OFD_NS}"><ofd:CompositeGraphicUnits>'
            '<ofd:CompositeGraphicUnit ID="50" Width="100" Height="100"><ofd:Content>'
            '<ofd:TextObject ID="51" Boundary="5 5 40 10" Font="1" Size="4"><ofd:TextCode X="0" Y="4">复合对象</ofd:TextCode></ofd:TextObject>'
            "</ofd:Content></ofd:CompositeGraphicUnit></ofd:CompositeGraphicUnits></ofd:Res>"
        ).encode()
        page = (
            f'<ofd:Page xmlns:ofd="{OFD_NS}"><ofd:Content><ofd:Layer ID="2">'
            '<ofd:CompositeObject ID="3" Boundary="10 100 100 100" CTM="0.5 0 0 0.5 0 0" ResourceID="50"/>'
            '<ofd:PageBlock ID="4"><ofd:TextObject ID="5" Boundary="10 10 40 10" Font="1" Size="4">'
            '<ofd:TextCode X="0" Y="4">页面块</ofd:TextCode></ofd:TextObject></ofd:PageBlock>'
            "</ofd:Layer></ofd:Content></ofd:Page>"
        ).encode()
        parts = OFDBuilder().parts([[]])
        parts["Doc_0/Pages/Page_0/Content.xml"] = page
        parts["Doc_0/DocumentRes.xml"] = resources
        parts["Doc_0/Document.xml"] = parts["Doc_0/Document.xml"].replace(
            b"<ofd:PublicRes>", b"<ofd:DocumentRes>DocumentRes.xml</ofd:DocumentRes><ofd:PublicRes>"
        )
        with ofdkit.open(zip_parts(parts)) as document:
            self.assertEqual(document.text(), "页面块\n\n复合对象")
            composite = next(run for run in document.pages[0].runs if run.text == "复合对象")
            self.assertEqual((composite.x, composite.y, composite.size), (10 + 0.5 * 5, 100 + 0.5 * 9, 2.0))

    def test_extract_text_helper(self):
        self.assertEqual(ofdkit.extract_text(OFDBuilder().build([[Text("你好", 20, 30)]])), "你好")


class HelperTest(unittest.TestCase):
    def test_delta_shorthand(self):
        self.assertEqual(_parse_deltas("g 3 1.5 2", 10), [1.5, 1.5, 1.5, 2.0])
        self.assertEqual(_parse_deltas("1 g 2 0.5", 2), [1.0, 0.5])
        self.assertEqual(len(_parse_deltas("g 1000000000 1", 5)), 5)
        self.assertEqual(_parse_deltas("x 1 g", 5), [1.0])

    def test_compose_applies_inner_first(self):
        scale_then_move = _compose((1, 0, 0, 1, 10, 20), (2, 0, 0, 2, 0, 0))
        self.assertEqual(scale_then_move, (2, 0, 0, 2, 10, 20))

    def test_object_transform_uses_boundary_origin(self):
        element = ET.fromstring('<TextObject Boundary="5 6 1 1" CTM="1 0 0 1 2 3"/>')
        self.assertEqual(_object_transform(element), (1.0, 0.0, 0.0, 1.0, 7.0, 9.0))


if __name__ == "__main__":
    unittest.main()
