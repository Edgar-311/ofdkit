import unittest

from ofdkit._xml import child, child_text, children, local_name, parse_xml
from ofdkit.errors import OFDFormatError, OFDLimitError


class ParseXmlTest(unittest.TestCase):
    def test_lookups_ignore_namespaces(self):
        root = parse_xml(b'<ofd:A xmlns:ofd="http://www.ofdspec.org/2016"><ofd:B>x</ofd:B><ofd:B>y</ofd:B></ofd:A>')
        self.assertEqual(local_name(root.tag), "A")
        self.assertEqual([b.text for b in children(root, "B")], ["x", "y"])
        self.assertEqual(child_text(root, "B"), "x")
        self.assertIsNone(child(root, "C"))

    def test_utf8_bom(self):
        root = parse_xml(b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?><a>\xe6\xb5\x8b\xe8\xaf\x95</a>')
        self.assertEqual(root.text, "测试")

    def test_declared_gbk_encoding(self):
        data = '<?xml version="1.0" encoding="GBK"?><a>测试样例</a>'.encode("gbk")
        self.assertEqual(parse_xml(data).text, "测试样例")

    def test_undeclared_gbk_bytes(self):
        self.assertEqual(parse_xml("<a>测试样例</a>".encode("gbk")).text, "测试样例")

    def test_repairs_empty_and_unbound_prefixes(self):
        data = (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<:eInvoice xmlns:=""><InvoiceNo><ofd:ObjectRef PageRef="1">5</ofd:ObjectRef></InvoiceNo></:eInvoice>'
        )
        root = parse_xml(data)
        self.assertEqual(local_name(root.tag), "eInvoice")
        reference = child(child(root, "InvoiceNo"), "ObjectRef")
        self.assertEqual(reference.get("PageRef"), "1")
        self.assertEqual(reference.text, "5")

    def test_rejects_doctype(self):
        data = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>'
        with self.assertRaises(OFDLimitError):
            parse_xml(data)

    def test_broken_xml_raises_format_error(self):
        with self.assertRaises(OFDFormatError):
            parse_xml(b"<a><b></a>")


if __name__ == "__main__":
    unittest.main()
