"""Publication links and support files must be present in versioned beta packages."""
import json
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
CHANNEL = "https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20"
MANIFEST = json.loads((BASE / "release.json").read_text(encoding="utf-8"))
VERSION = MANIFEST["integration"]
RELEASE = f"https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v{VERSION}"
NOTES_DIRECTORY = "beta" if "-beta." in VERSION else "release"
NOTES = BASE / f"docs/{NOTES_DIRECTORY}/RELEASE-NOTES-v{VERSION}.md"

class PublicBetaPublicationTests(unittest.TestCase):
    def test_invite_in_distribution_docs(self):
        for file in (BASE / "README.md", BASE / "INSTALLATION.md",
                     BASE / "docs/beta/START-HERE.md",
                     BASE / "docs/beta/SMARTTHINGS-CHANNEL.md",
                     NOTES,
                     BASE / "docs/beta/COMMUNITY-ANNOUNCEMENT.md"):
            self.assertIn(CHANNEL, file.read_text(encoding="utf-8"), str(file))
    def test_release_link_in_distribution_docs(self):
        if "-candidate-v" in MANIFEST["release_stage"]:
            self.skipTest("release candidate not published yet")
        for file in (BASE / "README.md", BASE / "INSTALLATION.md",
                     BASE / "docs/beta/START-HERE.md",
                     BASE / f"docs/beta/RELEASE-NOTES-v{VERSION}.md"):
            self.assertIn(RELEASE, file.read_text(encoding="utf-8"), str(file))
    def test_release_stage_never_enables_power(self):
        config = json.loads((BASE / "release.json").read_text())
        self.assertEqual(config["integration"], VERSION)
        self.assertEqual(config["power_control_default"], "disabled")
        self.assertEqual(config["smartthings_beta_channel"]["invitation_url"], CHANNEL)
    def test_no_angle_bracket_powershell_hub_placeholder(self):
        for file in (BASE / "INSTALLATION.md", BASE / "docs/beta/START-HERE.md",
                     BASE / "windows-agent/README.md"):
            text = file.read_text()
            self.assertNotIn("-HubIPv4 <", text)

if __name__ == "__main__":
    unittest.main()
