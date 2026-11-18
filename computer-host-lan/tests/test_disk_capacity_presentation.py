"""Verify additive disk capacity capability, translated presentation and legacy disk percent."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "edge-driver" / "custom-capabilities"


class DiskCapacityPresentationTests(unittest.TestCase):
    def test_existing_percent_retained_and_total_capacity_added(self):
        definition = json.loads((CAP / "computerDiskUsage.json").read_text())
        attrs = definition["attributes"]
        self.assertIn("diskUsage", attrs)
        self.assertEqual(attrs["diskUsage"]["schema"]["properties"]["value"]["maximum"], 100)
        self.assertIn("diskTotalGiB", attrs)
        total = attrs["diskTotalGiB"]["schema"]
        self.assertEqual(total["properties"]["value"]["type"], "number")
        self.assertEqual(total["properties"]["value"]["minimum"], 0)
        self.assertIn("value", total["required"])
        self.assertFalse(total["additionalProperties"])

    def test_presentation_has_both_values_and_unmodified_percent_automation(self):
        p = json.loads((CAP / "computerDiskUsage.presentation.json").read_text())
        labels = [v["state"]["label"] for v in p["detailView"]]
        self.assertEqual(labels, ["{{diskUsage.value}} %", "{{diskTotalGiB.value}} GiB"])
        self.assertEqual(p["automation"]["conditions"][0]["numberField"]["value"], "diskUsage.value")
        self.assertEqual(p["automation"]["conditions"][0]["numberField"]["range"], [0, 100])
        for lang in ("en", "de"):
            translation = json.loads((CAP / f"computerDiskUsage.{lang}.json").read_text())
            self.assertIn("diskUsage", translation["attributes"])
            self.assertIn("diskTotalGiB", translation["attributes"])


if __name__ == "__main__":
    unittest.main()
