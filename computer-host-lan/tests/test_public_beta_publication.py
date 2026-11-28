"""Publication and channel separation in the canonical distribution docs."""
import json
from pathlib import Path
import unittest

from scripts.ci.user_docs import notes_path

BASE = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((BASE / "release.json").read_text(encoding="utf-8"))
VERSION = MANIFEST["integration"]
CHANNEL = "https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20"
RELEASE = f"https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v{VERSION}"
NOTES = BASE / notes_path(VERSION)


class PublicBetaPublicationTests(unittest.TestCase):
    def test_invite_in_distribution_docs(self):
        for file in (BASE / "README.md", BASE / "docs/smartthings.md", NOTES):
            self.assertIn(CHANNEL, file.read_text(encoding="utf-8"), str(file))

    def test_release_link_in_distribution_docs(self):
        # The versioned download link is required before and after publication.
        for file in (BASE / "README.md", BASE / "docs/install-linux.md",
                     BASE / "docs/install-windows.md", BASE / "docs/testing.md",
                     BASE / "SECURITY.md", NOTES):
            self.assertIn(RELEASE, file.read_text(encoding="utf-8"), str(file))

    def test_release_stage_never_enables_power(self):
        self.assertEqual(MANIFEST["power_control_default"], "disabled")
        self.assertEqual(MANIFEST["smartthings_beta_channel"]["invitation_url"], CHANNEL)
        self.assertNotEqual(MANIFEST["last_published"]["url"], CHANNEL)
        self.assertIn("separate", NOTES.read_text(encoding="utf-8").lower())

    def test_no_angle_bracket_powershell_hub_placeholder(self):
        for file in (BASE / "docs/install-windows.md", BASE / "docs/upgrade.md",
                     BASE / "docs/troubleshooting.md"):
            self.assertNotIn("-HubIPv4 <", file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
