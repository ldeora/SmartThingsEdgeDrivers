"""Four-value presentation and schema regressions for existing capabilities."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "edge-driver" / "custom-capabilities"


class FourMetricPresentationTests(unittest.TestCase):
    def test_schema_and_readouts(self):
        for base, prefix in (("computerMemoryUsage", "memory"),
                             ("computerDiskUsage", "disk")):
            with self.subTest(capability=base):
                definition = json.loads((CAP / (base + ".json")).read_text())
                keys = [prefix + "Usage", prefix + "TotalGiB",
                        prefix + "UsedGiB", prefix + "AvailableGiB"]
                self.assertEqual(set(definition["attributes"]), set(keys))
                self.assertEqual(definition["commands"], {})
                self.assertEqual(definition["attributes"][keys[0]]["schema"]["properties"]["value"]["maximum"], 100)
                for key in keys[1:]:
                    attr = definition["attributes"][key]
                    self.assertEqual(attr["enumCommands"], [])
                    self.assertEqual(attr["schema"]["properties"]["value"]["type"], "number")
                    self.assertEqual(attr["schema"]["properties"]["value"]["minimum"], 0)
                    self.assertFalse(attr["schema"]["additionalProperties"])
                    self.assertEqual(attr["schema"]["required"], ["value"])
                view = json.loads((CAP / (base + ".presentation.json")).read_text())
                self.assertEqual(len(view["detailView"]), 4)
                expected = ["{{" + keys[0] + ".value}} %"] + [
                    "{{" + key + ".value}} GiB" for key in keys[1:]
                ]
                self.assertEqual([x["state"]["label"] for x in view["detailView"]], expected)
                self.assertEqual([x["label"] for x in view["detailView"]],
                                 ["{{i18n.attributes." + key + ".label}}" for key in keys])
                self.assertEqual(view["automation"]["conditions"][0]["numberField"]["value"],
                                 prefix + "Usage.value")
                self.assertEqual(view["automation"]["conditions"][0]["numberField"]["range"], [0, 100])
                self.assertEqual(len(view["dashboard"]["states"]), 1)
                for lang in ("en", "de"):
                    translation = json.loads((CAP / (base + "." + lang + ".json")).read_text())
                    self.assertEqual(set(translation["attributes"]), set(keys))
                    self.assertTrue(all(translation["attributes"][k]["label"] for k in keys))


if __name__ == "__main__":
    unittest.main()
