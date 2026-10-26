import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .ofdbuilder import OFDBuilder, Text
from .test_invoice import DIGITAL_INVOICE_TAG, _values_page

HAS_MCP = importlib.util.find_spec("mcp") is not None


class _Files(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.invoice = self.root / "invoice.ofd"
        self.invoice.write_bytes(OFDBuilder().build([_values_page()], custom_tag=DIGITAL_INVOICE_TAG))
        self.plain = self.root / "plain.ofd"
        self.plain.write_bytes(OFDBuilder().build([[Text("第一页", 20, 30)], [Text("第二页", 20, 30)]]))

    def tearDown(self):
        self.directory.cleanup()


@unittest.skipUnless(HAS_MCP, "mcp is not installed")
class InProcessTest(_Files):
    def call(self, name, arguments, root=None):
        from mcp import Client

        from ofdkit.mcp_server import create_server

        async def go():
            async with Client(create_server(root=root)) as client:
                return await client.call_tool(name, arguments)

        return asyncio.run(go())

    def test_tools_are_listed_as_read_only(self):
        from mcp import Client

        from ofdkit.mcp_server import create_server

        async def go():
            async with Client(create_server()) as client:
                return await client.list_tools()

        tools = {tool.name: tool for tool in asyncio.run(go()).tools}
        self.assertEqual(set(tools), {"read_ofd_text", "read_ofd_invoice", "ofd_info", "list_ofd_invoices"})
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)

    def test_read_invoice(self):
        result = self.call("read_ofd_invoice", {"path": str(self.invoice)})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["invoice_number"], "00000000000000000001")
        self.assertEqual(json.loads(result.content[0].text)["total_amount"], "106.00")

    def test_read_invoice_on_plain_file_is_an_error(self):
        result = self.call("read_ofd_invoice", {"path": str(self.plain)})
        self.assertTrue(result.is_error)
        self.assertIn("read_ofd_text", result.content[0].text)

    def test_read_text_with_page_range(self):
        self.assertEqual(self.call("read_ofd_text", {"path": str(self.plain)}).content[0].text, "第一页\n\n第二页")
        result = self.call("read_ofd_text", {"path": str(self.plain), "first_page": 2})
        self.assertEqual(result.content[0].text, "第二页")
        result = self.call("read_ofd_text", {"path": str(self.plain), "first_page": 5})
        self.assertTrue(result.is_error)

    def test_damaged_page_in_range_is_reported(self):
        from .ofdbuilder import zip_parts

        parts = OFDBuilder().parts([[Text("一", 20, 30)], [Text("二", 20, 30)]])
        parts["Doc_0/Pages/Page_0/Content.xml"] = b"<broken"
        damaged = self.root / "damaged.ofd"
        damaged.write_bytes(zip_parts(parts))
        result = self.call("read_ofd_text", {"path": str(damaged), "first_page": 1, "last_page": 2})
        self.assertFalse(result.is_error)
        self.assertIn("[page 1 could not be read", result.content[0].text)
        self.assertTrue(result.content[0].text.endswith("二"))

    def test_read_text_markdown(self):
        result = self.call("read_ofd_text", {"path": str(self.invoice), "markdown": True})
        self.assertTrue(result.content[0].text.startswith("## 发票信息"))

    def test_info_and_folder_listing(self):
        info = self.call("ofd_info", {"path": str(self.plain)}).structured_content
        self.assertEqual(len(info["pages"]), 2)
        listing = self.call("list_ofd_invoices", {"folder": str(self.root)}).structured_content
        self.assertEqual(listing["summary"]["invoices"], 1)
        self.assertEqual(listing["summary"]["without_invoice_data"], 1)
        self.assertFalse(listing["truncated"])

    def test_root_restricts_paths(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        other = Path(outside.name) / "other.ofd"
        other.write_bytes(self.plain.read_bytes())
        result = self.call("read_ofd_text", {"path": str(other)}, root=self.root)
        self.assertTrue(result.is_error)
        self.assertIn("outside the allowed folder", result.content[0].text)
        result = self.call("read_ofd_text", {"path": str(self.root / ".." / self.root.name / "plain.ofd")}, root=self.root)
        self.assertFalse(result.is_error)

    def test_missing_file(self):
        result = self.call("ofd_info", {"path": str(self.root / "missing.ofd")})
        self.assertTrue(result.is_error)
        self.assertIn("does not exist", result.content[0].text)


@unittest.skipUnless(HAS_MCP, "mcp is not installed")
class StdioHandshakeTest(_Files):
    """Speak the initialize-handshake protocol over real stdio, as most AI apps do."""

    def test_handshake_list_and_call(self):
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "read_ofd_invoice", "arguments": {"path": str(self.invoice)}},
            },
        ]
        process = subprocess.Popen(
            [sys.executable, "-m", "ofdkit", "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            responses = {}
            for request in requests:
                process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
                process.stdin.flush()
                if "id" in request:
                    while True:
                        line = process.stdout.readline()
                        self.assertTrue(line, process.stderr.read().decode("utf-8", "replace") if process.poll() is not None else "no response")
                        message = json.loads(line)
                        if message.get("id") == request["id"]:
                            responses[request["id"]] = message
                            break
        finally:
            process.stdin.close()
            process.wait(timeout=30)
            process.stdout.close()
            process.stderr.close()

        initialize = responses[1]["result"]
        self.assertEqual(initialize["protocolVersion"], "2025-06-18")
        self.assertEqual(initialize["serverInfo"]["name"], "ofdkit")
        self.assertIn("tools", initialize["capabilities"])
        self.assertEqual(len(responses[2]["result"]["tools"]), 4)
        call = responses[3]["result"]
        self.assertFalse(call.get("isError", False))
        self.assertEqual(call["structuredContent"]["issue_date"], "2026-01-02")


class MissingExtraTest(unittest.TestCase):
    @unittest.skipIf(HAS_MCP, "mcp is installed")
    def test_helpful_message_without_mcp(self):
        process = subprocess.run([sys.executable, "-m", "ofdkit", "mcp"], capture_output=True, timeout=60)
        self.assertEqual(process.returncode, 2)
        self.assertIn(b'pip install "ofdkit[mcp]"', process.stderr)


if __name__ == "__main__":
    unittest.main()
