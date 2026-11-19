"""Guard the top-level beta version independently of internal agent versions."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BetaReleaseVersionTests(unittest.TestCase):
    def test_beta_version_and_internal_versions(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        self.assertRegex(manifest["integration"], r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertEqual(manifest["agent"], "0.4.2-beta.1")
        self.assertEqual(manifest["edge_driver"], "0.4.2-beta.1")
        self.assertRegex(manifest["windows_agent"], r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertEqual(manifest["release_stage"], f"beta-candidate-v{manifest['integration']}")
        self.assertIn(f'<Version>{manifest["windows_agent"]}</Version>', (ROOT / 'windows-agent/ComputerHost.WindowsAgent/ComputerHost.WindowsAgent.csproj').read_text())
        self.assertIn(f'#define IntegrationVersion "{manifest["integration"]}"', (ROOT / 'windows-agent/installer/ComputerHostLAN.iss').read_text())
        self.assertEqual(manifest["agent_protocol"], 2)
        self.assertEqual(manifest["power_control_default"], "disabled")

    def test_release_docs_consistent(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        for name in ["README.md", "CHANGELOG.md", "BETA-STATUS.md",
                     "INSTALLATION.md", "RELEASE-BRIEF.md"]:
            self.assertIn(version, (ROOT / name).read_text(encoding="utf-8"), name)
        self.assertTrue((ROOT / "docs/beta" / f"RELEASE-NOTES-v{version}.md").is_file())

if __name__ == "__main__":
    unittest.main()
