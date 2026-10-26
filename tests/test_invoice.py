"""Invoice extraction on synthetic files.

The pages here hold a plain list of fake values; only the custom tag structure matches
real e-invoices. See AGENTS.md: no invoice-like layouts, no real data.
"""

import json
import unittest

import ofdkit
from ofdkit.invoice import _amount, _date

from .ofdbuilder import OFD_NS, OFDBuilder, Text

FP_NS = "http://www.edrm.org.cn/schema/e-invoice/2019"


def _values_page():
    values = {
        11: "00000000000000000001",
        12: "2026年01月02日",
        13: "测试单位甲",
        14: "testbuyer0001",
        15: "测试单位乙",
        16: "TESTSELLER0002",
        17: "¥",
        18: "100.00",
        19: "6.00",
        20: "￥106.00",
        21: "*测试*服务",
        22: "项目",
        23: "6%",
        24: "100.00",
        25: "6.00",
        26: "测试人员",
    }
    return [Text(text, 20, 20 + 8 * index, id=object_id) for index, (object_id, text) in enumerate(values.items())]


def _refs(*object_ids, page="1"):
    return "".join(f'<ofd:ObjectRef PageRef="{page}">{object_id}</ofd:ObjectRef>' for object_id in object_ids)


DIGITAL_INVOICE_TAG = (
    f'<ofd:root xmlns:ofd="{OFD_NS}" version="1.0">'
    f"<ofd:InvoiceNo>{_refs(11)}</ofd:InvoiceNo>"
    f"<ofd:IssueDate>{_refs(12)}</ofd:IssueDate>"
    f"<ofd:Buyer><ofd:BuyerName>{_refs(13)}</ofd:BuyerName><ofd:BuyerTaxID>{_refs(14)}</ofd:BuyerTaxID></ofd:Buyer>"
    f"<ofd:Seller><ofd:SellerName>{_refs(15)}</ofd:SellerName><ofd:SellerTaxID>{_refs(16)}</ofd:SellerTaxID></ofd:Seller>"
    f"<ofd:TaxExclusiveTotalAmount>{_refs(17, 18)}</ofd:TaxExclusiveTotalAmount>"
    f"<ofd:TaxTotalAmount>{_refs(19)}</ofd:TaxTotalAmount>"
    f"<ofd:TaxInclusiveTotalAmount>{_refs(20)}</ofd:TaxInclusiveTotalAmount>"
    f"<ofd:InvoiceClerk>{_refs(26)}</ofd:InvoiceClerk>"
    f"<ofd:Item>{_refs(21, 22)}</ofd:Item>"
    f"<ofd:TaxScheme>{_refs(23)}</ofd:TaxScheme>"
    f"<ofd:Amount>{_refs(24)}</ofd:Amount>"
    f"<ofd:TaxAmount>{_refs(25)}</ofd:TaxAmount>"
    "</ofd:root>"
)


class DigitalInvoiceTagsTest(unittest.TestCase):
    def setUp(self):
        data = OFDBuilder().build([_values_page()], custom_tag=DIGITAL_INVOICE_TAG)
        with ofdkit.open(data) as document:
            self.invoice = document.invoice()

    def test_fields(self):
        invoice = self.invoice
        self.assertEqual(invoice.invoice_number, "00000000000000000001")
        self.assertEqual(invoice.issue_date, "2026-01-02")
        self.assertEqual(invoice.buyer.name, "测试单位甲")
        self.assertEqual(invoice.buyer.tax_id, "TESTBUYER0001")
        self.assertEqual(invoice.seller.name, "测试单位乙")
        self.assertEqual(invoice.issuer, "测试人员")
        self.assertEqual(invoice.sources, ["custom_tags"])
        self.assertEqual(invoice.warnings, [])

    def test_amounts_lose_currency_signs(self):
        invoice = self.invoice
        self.assertEqual((invoice.amount_without_tax, invoice.tax_amount, invoice.total_amount), ("100.00", "6.00", "106.00"))

    def test_flat_line_item_joins_wrapped_name(self):
        (item,) = self.invoice.items
        self.assertEqual(item.name, "*测试*服务项目")
        self.assertEqual((item.tax_rate, item.amount, item.tax_amount), ("6%", "100.00", "6.00"))

    def test_to_dict_is_json_ready(self):
        data = json.loads(json.dumps(self.invoice.to_dict(include_raw=True), ensure_ascii=False))
        self.assertEqual(data["buyer"]["name"], "测试单位甲")
        self.assertEqual(data["raw"]["Buyer/BuyerName"], ["测试单位甲"])
        self.assertNotIn("raw", self.invoice.to_dict())


class EInvoiceSchemaTest(unittest.TestCase):
    def test_goods_infos_and_fp_namespace(self):
        page = [Text("测试物品一", 20, 20, id=1), Text("测试物品二", 20, 30, id=2), Text("00000002", 20, 40, id=3)]

        def goods(object_id, amount):
            return (
                "<fp:GoodsInfo>"
                f'<fp:Item><fp:ObjectRef PageRef="1">{object_id}</fp:ObjectRef></fp:Item>'
                f"<fp:Amount>{amount}</fp:Amount>"
                "</fp:GoodsInfo>"
            )

        tag = (
            f'<fp:eInvoice xmlns:fp="{FP_NS}" version="1.0">'
            '<fp:InvoiceNo><fp:ObjectRef PageRef="1">3</fp:ObjectRef></fp:InvoiceNo>'
            "<fp:Note></fp:Note>"
            f"<fp:GoodsInfos>{goods(1, '1.00')}{goods(2, '2.00')}</fp:GoodsInfos>"
            "</fp:eInvoice>"
        )
        invoice = ofdkit.extract_invoice(OFDBuilder().build([page], custom_tag=tag))
        self.assertEqual(invoice.invoice_number, "00000002")
        self.assertIsNone(invoice.note)
        self.assertEqual([(item.name, item.amount) for item in invoice.items], [("测试物品一", "1.00"), ("测试物品二", "2.00")])

    def test_reference_without_page_is_found_on_any_page(self):
        tag = f'<ofd:root xmlns:ofd="{OFD_NS}"><ofd:InvoiceNo><ofd:ObjectRef>31</ofd:ObjectRef></ofd:InvoiceNo></ofd:root>'
        data = OFDBuilder().build([[Text("首页", 20, 20)], [Text("00000031", 20, 20, id=31)]], custom_tag=tag)
        self.assertEqual(ofdkit.extract_invoice(data).invoice_number, "00000031")


class SourcesTest(unittest.TestCase):
    def test_attachment_values_win_over_tags(self):
        tag = f'<ofd:root xmlns:ofd="{OFD_NS}"><ofd:InvoiceNo>{_refs(11)}</ofd:InvoiceNo></ofd:root>'
        attachment = (
            "invoice.xml",
            f'<eInvoice xmlns:fp="{FP_NS}"><InvoiceNo>00000009</InvoiceNo><Buyer><BuyerName>测试单位丙</BuyerName></Buyer></eInvoice>',
        )
        data = OFDBuilder().build([_values_page()], custom_tag=tag, attachment=attachment)
        invoice = ofdkit.extract_invoice(data)
        self.assertEqual(invoice.invoice_number, "00000009")
        self.assertEqual(invoice.buyer.name, "测试单位丙")
        self.assertEqual(invoice.sources, ["attachment", "custom_tags"])

    def test_custom_data_alone(self):
        builder = OFDBuilder(
            custom_data={
                "发票号码": "00000003",
                "开票日期": "2026年03月04日",
                "合计金额": "10",
                "合计税额": "1",
                "价税合计": "11",
                "销售方地址、 电话": "测试地址 000",
            }
        )
        invoice = ofdkit.extract_invoice(builder.build([[Text("测试样例", 20, 20)]]))
        self.assertEqual(invoice.invoice_number, "00000003")
        self.assertEqual(invoice.issue_date, "2026-03-04")
        self.assertEqual(invoice.total_amount, "11")
        self.assertEqual(invoice.seller.address_phone, "测试地址 000")
        self.assertEqual(invoice.sources, ["custom_data"])

    def test_totals_that_do_not_add_up_give_a_warning(self):
        builder = OFDBuilder(custom_data={"发票号码": "1", "合计金额": "10.00", "合计税额": "1.00", "价税合计": "12.00"})
        invoice = ofdkit.extract_invoice(builder.build([[Text("测试样例", 20, 20)]]))
        self.assertEqual(len(invoice.warnings), 1)

    def test_not_an_invoice(self):
        self.assertIsNone(ofdkit.extract_invoice(OFDBuilder().build([[Text("普通文档", 20, 20)]])))
        tag = f'<LogicalStructure xmlns="{OFD_NS}"><逻辑结构>章节</逻辑结构></LogicalStructure>'
        self.assertIsNone(ofdkit.extract_invoice(OFDBuilder().build([[Text("普通文档", 20, 20)]], custom_tag=tag)))


class _Page:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _Document:
    def __init__(self, text):
        self.pages = [_Page(text)]


class InvoiceTypeTest(unittest.TestCase):
    """The type comes from the title line; stub pages keep these tests free of invoice-like files."""

    def kind(self, text):
        from ofdkit.invoice import _invoice_type

        return _invoice_type(_Document(text))

    def test_digital_invoice_titles(self):
        self.assertEqual(self.kind("电子发票（增值税专用发票）   发票号码：00000001"), "电子发票（增值税专用发票）")
        self.assertEqual(self.kind("测试样例\n电子发票(普通发票)"), "电子发票（普通发票）")
        self.assertEqual(self.kind("电子发票 （ 铁路电子客票 ）"), "电子发票（铁路电子客票）")

    def test_older_titles_keep_their_region(self):
        self.assertEqual(self.kind("测试增值税电子普通发票\n机器编号：0"), "测试增值税电子普通发票")
        self.assertEqual(self.kind("增值税电子普通发票(通行费)"), "增值税电子普通发票（通行费）")

    def test_no_title(self):
        self.assertIsNone(self.kind("测试样例\n普通文档"))
        self.assertIsNone(self.kind("这不是增值税电子普通发票的标题，因为它在句子中间"))

    def test_field_is_in_the_output(self):
        builder = OFDBuilder(custom_data={"发票号码": "00000006"})
        invoice = ofdkit.extract_invoice(builder.build([[Text("测试样例", 20, 20)]]))
        self.assertIn("invoice_type", invoice.to_dict())
        self.assertIsNone(invoice.invoice_type)


class NormalisationTest(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(_date("2026年1月2日"), "2026-01-02")
        self.assertEqual(_date("20260102"), "2026-01-02")
        self.assertEqual(_date("2026/01/02"), "2026-01-02")
        self.assertEqual(_date("2026-01-02 10:11:12"), "2026-01-02")
        self.assertEqual(_date("明天"), "明天")
        self.assertEqual(_date("2026年13月02日"), "2026年13月02日")

    def test_amounts(self):
        self.assertEqual(_amount("¥1,234.50"), "1234.50")
        self.assertEqual(_amount("￥ -12.30 元"), "-12.30")
        self.assertEqual(_amount("免税"), "免税")
        self.assertIsNone(_amount(None))


if __name__ == "__main__":
    unittest.main()
