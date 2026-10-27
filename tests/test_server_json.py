"""server.json, the listing in the official MCP Registry, must agree with the package."""

import json
import re
import unittest
from pathlib import Path

from ofdkit.cli import COMMANDS

ROOT = Path(__file__).resolve().parent.parent
SERVER_JSON = ROOT / "server.json"


@unittest.skipUnless(SERVER_JSON.exists(), "not running from a source checkout")
class ServerJsonTest(unittest.TestCase):
    def setUp(self):
        self.server = json.loads(SERVER_JSON.read_text(encoding="utf-8"))
        self.package = self.server["packages"][0]
        self.pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    def test_readme_proves_ownership(self):
        # The registry looks for this token in the README that PyPI shows.
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, rf"mcp-name: {re.escape(self.server['name'])}(\s|-->)")

    def test_package_is_this_project(self):
        name = re.search(r'^name = "([^"]+)"', self.pyproject, re.MULTILINE)[1]
        self.assertEqual((self.package["registryType"], self.package["identifier"]), ("pypi", name))
        self.assertEqual(self.server["name"], f"io.github.Edgar-311/{name}")

    def test_command_runs_the_mcp_server_with_the_extra(self):
        extra = re.search(r'^mcp = \["([^"]+)"\]', self.pyproject, re.MULTILINE)[1]
        self.assertEqual(self.package["runtimeHint"], "uvx")
        self.assertEqual(self.package["runtimeArguments"][0]["name"], "--with")
        self.assertEqual(self.package["runtimeArguments"][0]["value"], extra)
        command = self.package["packageArguments"][0]["value"]
        self.assertEqual(command, "mcp")
        self.assertIn(command, COMMANDS)

    def test_versions_agree(self):
        # The release workflow sets both from the tag; keep them equal in the file too.
        self.assertEqual(self.server["version"], self.package["version"])

    def test_registry_limits(self):
        self.assertLessEqual(len(self.server["description"]), 100)
        self.assertLessEqual(len(self.server["title"]), 100)


if __name__ == "__main__":
    unittest.main()
