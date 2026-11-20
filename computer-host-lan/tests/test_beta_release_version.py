"""Release-version and install/upgrade consistency checks (beta, RC, stable)."""
from pathlib import Path
import json
import re
import unittest

from scripts.ci.build_windows_kit import release_kind

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-(?:beta|rc)\.\d+)?$")


def release_notes(version):
    directory = "beta" if release_kind(version) == "beta" else "release"
    return f"docs/{directory}/RELEASE-NOTES-v{version}.md"


class ReleaseVersionTests(unittest.TestCase):
    def test_supported_version_strings(self):
        for version, kind in (
            ("0.5.6-beta.1", "beta"), ("1.0.0-rc.1", "rc"),
            ("1.0.0", "stable"), ("2.3.12-rc.10", "rc")
        ):
            with self.subTest(version=version):
                self.assertEqual(release_kind(version), kind)
        for version in ("", "1.0", "1.0.0-dev.1", "1.0.0-rc",
                        "v1.0.0", "1.0.0-rc.1-extra"):
            with self.subTest(invalid=version):
                with self.assertRaises(ValueError):
                    release_kind(version)

    def test_release_and_internal_versions_match(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        for component in ("integration", "agent", "edge_driver", "windows_agent"):
            self.assertRegex(manifest[component], VERSION, component)
        version = manifest["integration"]
        kind = release_kind(version)
        self.assertIn(manifest["release_stage"],
                      (f"{kind}-candidate-v{version}", f"{kind}-published-v{version}"))
        self.assertEqual(manifest["release_candidate_tag"], f"computer-host-lan-v{version}")
        if manifest["release_stage"] == f"{kind}-published-v{version}":
            self.assertEqual(manifest.get("github_release", manifest.get("github_prerelease")),
                             f"https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v{version}")
        self.assertIn(f'<Version>{manifest["windows_agent"]}</Version>',
                      (ROOT / "windows-agent/ComputerHost.WindowsAgent/ComputerHost.WindowsAgent.csproj").read_text())
        self.assertIn(f'AgentVersion = "{manifest["windows_agent"]}"',
                      (ROOT / "windows-agent/ComputerHost.WindowsAgent/AgentContract.cs").read_text())
        self.assertIn(f'VERSION = "{manifest["agent"]}"',
                      (ROOT / "agent/linux_host_agent.py").read_text())
        self.assertIn(f'DRIVER_VERSION = "{manifest["edge_driver"]}"',
                      (ROOT / "edge-driver/src/computerhost/constants.lua").read_text())
        iss = (ROOT / "windows-agent/installer/ComputerHostLAN.iss").read_text()
        self.assertIn(f'#define IntegrationVersion "{version}"', iss)
        self.assertIn(f'#define WindowsAgentVersion "{manifest["windows_agent"]}"', iss)
        self.assertIn('ExpectedVersion "{#WindowsAgentVersion}"', iss)
        self.assertIn('"SmartThings-ComputerHost/"..C.DRIVER_VERSION',
                      (ROOT / "edge-driver/src/computerhost/api.lua").read_text())
        self.assertIn('server_version = "LinuxHostAgent/" + VERSION',
                      (ROOT / "agent/linux_host_agent.py").read_text())
        self.assertEqual(manifest["agent_protocol"], 2)
        self.assertEqual(manifest["power_control_default"], "disabled")

    def test_published_docs_reference_current_release(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        if manifest["release_stage"] != f"{release_kind(version)}-published-v{version}":
            self.skipTest("release is not yet published")
        release_url = manifest.get("github_release", manifest.get("github_prerelease"))
        for name in ("README.md", "INSTALLATION.md",
                     "windows-agent/README.md", "docs/beta/START-HERE.md",
                     release_notes(version)):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(release_url, content, name)
            opening = "\n".join(content.splitlines()[:6]).lower()
            self.assertNotIn("not yet published", opening, name)
            self.assertNotIn("unpublished", opening, name)

    def test_release_docs_consistent(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        for name in ("README.md", "CHANGELOG.md", "INSTALLATION.md"):
            self.assertIn(version, (ROOT / name).read_text(encoding="utf-8"), name)
        self.assertTrue((ROOT / release_notes(version)).is_file(), release_notes(version))


if __name__ == "__main__":
    unittest.main()
