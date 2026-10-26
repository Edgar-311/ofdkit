"""Check ofdkit against the expected outputs in the ofd-samples repository.

Set OFD_SAMPLES_DIR to a checkout of https://github.com/Edgar-311/ofd-samples, or keep
the checkout next to this repository as ../ofd-samples. CI checks it out automatically.
"""

import json
import os
import re
import unittest
from pathlib import Path

import ofdkit


def _samples_dir():
    configured = os.environ.get("OFD_SAMPLES_DIR")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parent.parent.parent / "ofd-samples")
    for candidate in candidates:
        if (candidate / "expected").is_dir():
            return candidate
    return None


SAMPLES = _samples_dir()


def _normalise(text):
    """Compare text ignoring blank lines and the amount of horizontal whitespace."""
    lines = (re.sub(r"[ \t　]+", " ", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


@unittest.skipIf(SAMPLES is None, "ofd-samples not found (set OFD_SAMPLES_DIR)")
class SamplesTest(unittest.TestCase):
    def test_all_samples(self):
        expected_files = sorted((SAMPLES / "expected").glob("*.json"))
        self.assertGreaterEqual(len(expected_files), 10)
        for path in expected_files:
            expected = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(sample=expected["name"]):
                self.check(SAMPLES / "samples" / f"{expected['name']}.ofd", expected)

    def check(self, ofd_path, expected):
        with ofdkit.open(ofd_path) as document:
            self.assertEqual(document.info.title, expected["doc_info"]["title"])
            self.assertEqual(document.info.custom_data, expected["doc_info"]["custom_data"])
            self.assertEqual(len(document.pages), len(expected["pages"]))
            for page, page_expected in zip(document.pages, expected["pages"]):
                self.assertEqual(page.id, page_expected["id"])
                if not page_expected["readable"]:
                    self.assertIsNone(page.location)
                    continue
                self.assertEqual((page.width, page.height), (page_expected["width"], page_expected["height"]))
                self.assertEqual(_normalise(page.text()), _normalise(page_expected["text"]))
                self.check_objects(page, page_expected["text_objects"])

            invoice = document.invoice()
            for key in ("custom_tag_values", "attachment_values"):
                if key in expected:
                    self.assertIsNotNone(invoice, key)
                    self.check_values(invoice, expected[key])

    def check_objects(self, page, objects):
        runs = page.runs
        for obj in objects:
            self.assertEqual(page.object_text(obj["id"]), obj["text"], obj["id"])
            found = [run for run in runs if run.object_id == obj["id"] and run.from_template == obj["from_template"]]
            for run_expected in obj["runs"]:
                matches = [
                    run
                    for run in found
                    if run.text == run_expected["text"]
                    and abs(run.x - run_expected["x"]) < 1e-3
                    and abs(run.y - run_expected["y"]) < 1e-3
                ]
                self.assertTrue(matches, f"object {obj['id']}: no run {run_expected} in {found}")
                self.assertAlmostEqual(matches[0].size, obj["size"], places=3)

    def check_values(self, invoice, values):
        items = [value for value in values if value["path"].startswith("GoodsInfos/")]
        for value in values:
            if value not in items:
                self.assertIn(value["value"], invoice.raw.get(value["path"], []), value["path"])
        names = [value["value"] for value in items if value["path"].endswith("/Item")]
        if names:
            self.assertEqual([item.name for item in invoice.items], names)


if __name__ == "__main__":
    unittest.main()
