"""Embedded device presentation regressions (#192).

An embedded deviceConfig replaces the presentation SmartThings would
otherwise generate. A capability that is missing from detailView disappears
from the device page, and one missing from automation disappears from
routines. These tests keep both lists complete for every profile.
"""
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "edge-driver" / "profiles"
CAPABILITIES = ROOT / "edge-driver" / "custom-capabilities"
STATUS = "oceancircle09600.computerHostStatus"
# Capabilities without any routine condition or action.
NO_AUTOMATION = {"refresh"}
# Capabilities whose only routine use is a command.
ACTION_ONLY = {"momentary"}


def load(name):
    return yaml.safe_load((PROFILES / name).read_text())


def entries(items):
    result = []
    for item in items or []:
        result.append((item["component"], item["capability"]))
        assert item.get("version") == 1, item
    return result


def profile_capabilities(profile):
    return [(component["id"], capability["id"])
            for component in profile["components"]
            for capability in component["capabilities"]]


class EmbeddedPresentationTests(unittest.TestCase):
    def test_monitoring_profiles_list_every_capability(self):
        for name in ("computer-host-linux.yaml", "computer-host-windows.yaml"):
            with self.subTest(profile=name):
                profile = load(name)
                config = profile["deviceConfig"]
                capabilities = profile_capabilities(profile)
                detail = entries(config["detailView"])
                automation = config["automation"]
                conditions = entries(automation["conditions"])
                actions = entries(automation["actions"])
                for listed in (detail, conditions, actions):
                    self.assertEqual(len(listed), len(set(listed)), "duplicate entry")
                    self.assertLessEqual(set(listed), set(capabilities), "unknown entry")
                self.assertEqual(set(detail), set(capabilities))
                expected_conditions = {item for item in capabilities
                                       if item[1] not in NO_AUTOMATION | ACTION_ONLY}
                self.assertEqual(set(conditions), expected_conditions)
                expected_actions = {("main", "switch")} | {
                    item for item in capabilities if item[1] in ACTION_ONLY}
                self.assertEqual(set(actions), expected_actions)
                # Wake, Restart and Sleep stay on the device page and in routines.
                for component in ("wake", "reboot", "suspend"):
                    self.assertIn((component, "momentary"), detail)
                    self.assertIn((component, "momentary"), actions)

    def test_tile_shows_host_status_and_keeps_switch(self):
        for name in ("computer-host-linux.yaml", "computer-host-windows.yaml"):
            with self.subTest(profile=name):
                dashboard = load(name)["deviceConfig"]["dashboard"]
                self.assertEqual(entries(dashboard["states"]), [("main", STATUS)])
                self.assertEqual(entries(dashboard["actions"]), [("main", "switch")])
                self.assertEqual(dashboard["basicPlus"], [])

    def test_basic_profile_keeps_generated_presentation(self):
        # The fallback profile has no Host Status capability to show.
        self.assertNotIn("deviceConfig", load("computer-host.yaml"))

    def test_custom_capabilities_have_the_listed_presentation_sections(self):
        for name in ("computer-host-linux.yaml", "computer-host-windows.yaml"):
            config = load(name)["deviceConfig"]
            conditions = {cap for _, cap in entries(config["automation"]["conditions"])}
            for _, capability in entries(config["detailView"]):
                if not capability.startswith("oceancircle09600."):
                    continue
                with self.subTest(profile=name, capability=capability):
                    base = capability.split(".", 1)[1]
                    view = json.loads((CAPABILITIES / (base + ".presentation.json")).read_text())
                    self.assertTrue(view["detailView"])
                    if capability in conditions:
                        self.assertTrue(view["automation"]["conditions"])
        status = json.loads((CAPABILITIES / "computerHostStatus.presentation.json").read_text())
        self.assertTrue(status["dashboard"]["states"])

    def test_unreachable_is_shown_as_inactive(self):
        view = json.loads((CAPABILITIES / "computerHostStatus.presentation.json").read_text())
        sections = [view["dashboard"]["states"][0]["alternatives"],
                    view["detailView"][0]["state"]["alternatives"],
                    view["automation"]["conditions"][0]["list"]["alternatives"]]
        for alternatives in sections:
            types = {item["key"]: item["type"] for item in alternatives}
            self.assertEqual(types["unreachable"], "inactive")
            for key in ("stopped", "suspended", "unknown"):
                self.assertEqual(types[key], "inactive")
            for key in ("running", "starting", "stopping", "suspending", "rebooting"):
                self.assertEqual(types[key], "active")


if __name__ == "__main__":
    unittest.main()
