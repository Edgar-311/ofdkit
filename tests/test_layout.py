"""Reading order on hand-placed runs. Coordinates are millimetres, y is the baseline."""

import unittest

from ofdkit.document import TextRun
from ofdkit.layout import page_text


def run(text, x, y, size=3.0, width=None):
    if width is None:
        width = sum(size if ord(char) > 0x2E80 else size / 2 for char in text)
    return TextRun(text=text, x=x, y=y, size=size, width=width)


def stack(text, x, y, step):
    return [run(char, x, y + index * step) for index, char in enumerate(text)]


class VerticalLabelTest(unittest.TestCase):
    def test_label_beside_rows_reads_as_one_word(self):
        runs = [*stack("购买方信息", 6, 35, 3.5), run("名称：测试单位甲", 20, 35), run("识别号：TEST0001", 20, 46)]
        self.assertEqual(page_text(runs), "购买方信息   名称：测试单位甲\n\n识别号：TEST0001")

    def test_two_labels_on_the_same_rows(self):
        runs = [*stack("购买方", 6, 35, 3.5), run("名称：甲", 20, 35), *stack("销售方", 106, 35, 3.5), run("名称：乙", 120, 35)]
        self.assertEqual(page_text(runs), "购买方   名称：甲   销售方   名称：乙")

    def test_widely_spaced_label_and_trailing_header_is_not_swallowed(self):
        # Older invoices spread labels over the rows; the table header below must stay whole.
        runs = [
            *stack("密码区", 120, 35, 6.35),
            run("0123456789", 130, 35),
            run("单", 120, 55),
            run("价", 126, 55),
            run("金额", 145, 55),
        ]
        text = page_text(runs)
        self.assertTrue(text.startswith("密码区   0123456789"), text)
        self.assertIn("单 价   金额", text)

    def test_table_column_of_single_characters_is_not_merged(self):
        rows = [[run("测试服务", 10, y), run("次", 60, y), run("4", 80, y), run("100.00", 100, y)] for y in (60, 65, 70)]
        text = page_text([r for row in rows for r in row])
        self.assertEqual(text.count("次"), 3)
        self.assertNotIn("次次", text)

    def test_text_drawn_one_character_at_a_time_is_not_merged(self):
        # Each character is its own run and they touch: these are two ordinary lines.
        line1 = [run(char, 20 + 3 * index, 40) for index, char in enumerate("新宋")]
        line2 = [run(char, 20 + 3 * index, 44) for index, char in enumerate("楷体")]
        self.assertEqual(page_text(line1 + line2), "新宋\n楷体")

    def test_latin_and_digits_are_never_labels(self):
        runs = [run("1", 10, 40), run("2", 10, 44), run("A", 10, 48)]
        self.assertEqual(page_text(runs), "1\n2\nA")


def column(lines, x, y, step=4.8):
    return [run(text, x, y + index * step) for index, text in enumerate(lines)]


LEFT = ["当前，随着信息技术的飞速发展和互联", "网的无限延伸，数字化、网络化、信息", "化已深刻影响着人们的工作和生活，社", "会已不可逆转地进入了大数据时代。"]
RIGHT = ["同时，各级单位的档案资源不断增加，", "对档案管理的规范化和智能化提出了更", "高的要求，迫切需要建设数字档案室，", "进一步提高信息化建设的能力。"]


class ColumnTest(unittest.TestCase):
    def test_two_prose_columns_read_column_by_column(self):
        text = page_text(column(LEFT, 12, 100) + column(RIGHT, 120, 100))
        self.assertEqual(text, "\n".join(LEFT) + "\n\n" + "\n".join(RIGHT))

    def test_heading_across_both_columns_ends_the_region(self):
        runs = column(LEFT, 12, 100) + column(RIGHT, 120, 100) + [run("跨两栏的标题文字跨两栏的标题文字跨两栏的标题文字跨两栏的标题文字跨两栏的标题", 12, 122)]
        text = page_text(runs)
        self.assertTrue(text.startswith("\n".join(LEFT)), text)
        self.assertTrue(text.endswith("跨两栏的标题"), text)

    def test_caption_in_smaller_type_is_read_after_the_columns(self):
        caption = run("图片说明", 70, 106, size=2.0)
        text = page_text(column(LEFT, 12, 100) + column(RIGHT, 120, 100) + [caption])
        self.assertEqual(text, "\n".join(LEFT) + "\n\n" + "\n".join(RIGHT) + "\n\n图片说明")

    def test_key_value_table_stays_row_by_row(self):
        rows = [("toolbar=1|0", "显示或隐藏工具栏。"), ("statusbar=1|0", "显示或隐藏状态栏。"), ("navpanes=1|0", "显示或隐藏导航面板。")]
        runs = [r for index, (key, value) in enumerate(rows) for r in (run(key, 20, 50 + 5 * index), run(value, 60, 50 + 5 * index))]
        self.assertEqual(page_text(runs), "toolbar=1|0   显示或隐藏工具栏。\nstatusbar=1|0   显示或隐藏状态栏。\nnavpanes=1|0   显示或隐藏导航面板。")

    def test_table_with_short_cells_stays_row_by_row(self):
        header = [run(text, x, 50) for text, x in (("项目名称", 10), ("单位", 60), ("数量", 80), ("金额", 100))]
        rows = [[run(f"测试项目{index}", 10, y), run("个", 60, y), run(str(index), 80, y), run("1.00", 100, y)] for index, y in ((1, 55), (2, 60), (3, 65))]
        text = page_text(header + [r for row in rows for r in row])
        self.assertEqual(text.splitlines()[1], "测试项目1   个   1   1.00")


if __name__ == "__main__":
    unittest.main()
