"""Guard the top-level beta version independently of internal agent versions."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]

class BetaReleaseVersionTests(unittest.TestCase):
    def test_beta_version_and_internal_versions(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        self.assertRegex(manifest["integration"], r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertRegex(manifest["agent"], r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertRegex(manifest["edge_driver"], r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertRegex(manifest["windows_agent"], r"^\d+\.\d+\.\d+-beta\.\d+$")
        self.assertEqual(manifest["release_stage"], f"beta-candidate-v{manifest['integration']}")
        self.assertEqual(manifest["release_candidate_tag"], f"computer-host-lan-v{manifest['integration']}")
        self.assertEqual(manifest["github_prerelease"], "https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1", "keep published beta URL until the new release exists")
        self.assertIn(f'<Version>{manifest["windows_agent"]}</Version>', (ROOT / 'windows-agent/ComputerHost.WindowsAgent/ComputerHost.WindowsAgent.csproj').read_text())
        self.assertIn(f'AgentVersion = "{manifest["windows_agent"]}"', (ROOT / 'windows-agent/ComputerHost.WindowsAgent/AgentContract.cs').read_text())
        self.assertIn(f'VERSION = "{manifest["agent"]}"', (ROOT / 'agent/linux_host_agent.py').read_text())
        self.assertIn(f'DRIVER_VERSION = "{manifest["edge_driver"]}"', (ROOT / 'edge-driver/src/computerhost/constants.lua').read_text())
        self.assertIn(f'#define IntegrationVersion "{manifest["integration"]}"', (ROOT / 'windows-agent/installer/ComputerHostLAN.iss').read_text())
        self.assertIn('"SmartThings-ComputerHost/"..C.DRIVER_VERSION', (ROOT / 'edge-driver/src/computerhost/api.lua').read_text())
        self.assertIn('server_version = "LinuxHostAgent/" + VERSION', (ROOT / 'agent/linux_host_agent.py').read_text())
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
