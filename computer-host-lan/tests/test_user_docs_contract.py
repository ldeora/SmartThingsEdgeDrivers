"""Documented preferences and states must track the actual profiles/capability."""
import json
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/smartthings.md"


class UserDocsContract(unittest.TestCase):
    def test_preference_table(self):
        rows = {}
        for line in GUIDE.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\| (.+) \(\x60([A-Za-z]+)\x60\) \| ([^|]+) \| ([^|]+) \|$", line)
            if match:
                title, name, default, explanation = match.groups()
                self.assertNotIn(name, rows)
                rows[name] = title, default.strip(), explanation.strip()
        for platform in ("linux", "windows"):
            profile = yaml.safe_load(
                (ROOT / f"edge-driver/profiles/computer-host-{platform}.yaml").read_text())
            prefs = {p["name"]: p for p in profile["preferences"]}
            self.assertEqual(set(rows), set(prefs), platform)
            for name, pref in prefs.items():
                with self.subTest(platform=platform, preference=name):
                    title, default, explanation = rows[name]
                    definition = pref["definition"]
                    expected = definition["default"]
                    expected = ("Empty" if expected == "" else
                                json.dumps(expected) if isinstance(expected, bool) else str(expected))
                    self.assertEqual(title, pref["title"])
                    self.assertEqual(default, expected)
                    if pref["preferenceType"] == "integer":
                        self.assertTrue(explanation.startswith(
                            f'{definition["minimum"]}–{definition["maximum"]};'))

    def test_all_host_status_values(self):
        section = GUIDE.read_text(encoding="utf-8").split("## Host Status and the switch", 1)[1]
        section = section.split("### Routines", 1)[0]
        rows = re.findall(r"^\| ([A-Z][a-z]+) \| [^|]+ \|$", section, re.M)
        capability = json.loads((ROOT / "edge-driver/custom-capabilities/computerHostStatus.json").read_text())
        states = capability["attributes"]["status"]["schema"]["properties"]["value"]["enum"]
        self.assertEqual(sorted(row.lower() for row in rows), sorted(states))


if __name__ == "__main__":
    unittest.main()
