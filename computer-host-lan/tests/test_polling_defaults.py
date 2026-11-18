"""Keep documented availability defaults and Lua fallback in sync."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "edge-driver"


class PollingDefaultsTests(unittest.TestCase):
    def test_20_second_default_in_all_profiles(self):
        for profile_name in ("computer-host", "computer-host-linux", "computer-host-windows"):
            with self.subTest(profile=profile_name):
                profile = yaml.safe_load((DRIVER / "profiles" / f"{profile_name}.yaml").read_text())
                prefs = {p["name"]: p for p in profile["preferences"]}
                availability = prefs["pollInterval"]["definition"]
                self.assertEqual(availability["default"], 20)
                self.assertEqual(availability["minimum"], 10)
                self.assertEqual(availability["maximum"], 300)
                self.assertEqual(prefs["telemetryInterval"]["definition"]["default"], 60)
                self.assertEqual(prefs["failureThreshold"]["definition"]["default"], 3)

    def test_lua_fallback_and_preference_override_remain_in_place(self):
        constants = (DRIVER / "src/computerhost/constants.lua").read_text()
        util = (DRIVER / "src/computerhost/util.lua").read_text()
        self.assertIn("M.DEFAULT_POLL_INTERVAL = 20", constants)
        self.assertIn("device.preferences.pollInterval", util)
        self.assertIn("or C.DEFAULT_POLL_INTERVAL", util)
        self.assertIn("math.max(10,math.min(300", util)


if __name__ == "__main__":
    unittest.main()
