import contextlib
import io
import unittest

from ofdkit import __version__
from ofdkit.cli import main


class VersionFlagTest(unittest.TestCase):
    def test_prints_version_and_exits_cleanly(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(__version__, out.getvalue())


if __name__ == "__main__":
    unittest.main()
