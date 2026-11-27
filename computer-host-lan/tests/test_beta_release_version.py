"""Release-version and install/upgrade consistency checks (beta, RC, stable)."""
from pathlib import Path
import json
import re
import tempfile
import unittest
from zipfile import ZipFile

from scripts.ci.build_windows_kit import build, release_kind

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
                     "windows-agent/README.md",
                     "docs/beta/START-HERE.md" if release_kind(version) == "beta"
                     else "docs/release/QUICK-START.md",
                     release_notes(version)):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(release_url, content, name)
            opening = "\n".join(content.splitlines()[:6]).lower()
            self.assertNotIn("not yet published", opening, name)
            self.assertNotIn("unpublished", opening, name)

    def test_rc_notes_match_stage_and_are_packaged_verbatim(self):
        """Current docs reflect publication status and are packaged exactly."""
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        if release_kind(version) != "rc":
            self.skipTest("publication-neutral RC notes apply to release candidates")
        notes_path = ROOT / release_notes(version)
        notes = notes_path.read_text(encoding="utf-8")
        release_url = (f"https://github.com/ldeora/SmartThingsEdgeDrivers/"
                       f"releases/tag/computer-host-lan-v{version}")
        self.assertIn(release_url, notes)
        if "linux_installer" in manifest:
            self.assertNotRegex(notes.lower(), r"not (?:yet )?published|planned rc\\.|once rc\.3 is published")
        elif manifest["release_stage"] == f"rc-published-v{version}":
            self.assertIn("Published:", notes)
            self.assertIn("immutable", notes.lower())
            self.assertNotIn("not yet published", notes.lower())
        else:
            self.assertIn("their presence does not by itself prove a release has been published", notes)
        self.assertIn("separate", notes.lower())
        for stale in ("not yet published", "not published yet",
                      "after this RC is published", "no GitHub release"):
            self.assertNotIn(stale.lower(), notes.lower())

        # The RC Windows fallback ZIP contains precisely this file, not a
        # differently staged or hard-coded release announcement.
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            published = temp / "publish"
            published.mkdir()
            (published / "ComputerHost.WindowsAgent.exe").write_bytes(b"test stub")
            (published / "appsettings.json").write_text("{}", encoding="utf-8")
            archive = build(published, temp / "out", "win-x64", "a" * 40)
            with ZipFile(archive) as zip_file:
                self.assertEqual(zip_file.read("docs/RELEASE-NOTES.md"), notes_path.read_bytes())
                if "linux_installer" in manifest:
                    quick = ROOT / "docs/release/WINDOWS-QUICK-START.md"
                    self.assertEqual(zip_file.read("docs/START-HERE.md"), quick.read_bytes())
                    # Every relative screenshot in the quick start must be
                    # present beside it in the fallback ZIP and checksummed.
                    import hashlib
                    images = re.findall(r"!\[[^\]]*\]\((images/windows-setup/[^)]+)\)",
                                        quick.read_text(encoding="utf-8"))
                    self.assertTrue(images, "Windows quick start screenshots missing")
                    sums = zip_file.read("FILES.sha256").decode("utf-8")
                    for rel in images:
                        member = "docs/" + rel
                        data = (quick.parent / rel).read_bytes()
                        self.assertEqual(zip_file.read(member), data)
                        self.assertIn(f"{hashlib.sha256(data).hexdigest()}  {member}\n", sums)
                    self.assertEqual(zip_file.read("docs/TEST-CHECKLIST.md"),
                                     (ROOT / "docs/release/RC3-READINESS.md").read_bytes())

    def test_published_rc1_warnings_survive_rc2_publication(self):
        """rc.1 remains downloadable and its security warning must remain."""
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        published_rc1_url = (
            "https://github.com/ldeora/SmartThingsEdgeDrivers/"
            "releases/tag/computer-host-lan-v1.0.0-rc.1"
        )
        # Do not skip just because the current prerelease advances to rc.2.
        self.assertNotEqual(manifest.get("github_prerelease"), published_rc1_url)
        required = {
            ("docs/history/RC2-AND-EARLIER.md" if "linux_installer" in manifest
             else "README.md"): ("#32", "rc.2", "rc.1"),
            "INSTALLATION.md": ("#32", "#33", "#44", "rc.2", "rc.1"),
            "SECURITY.md": ("#30", "#31", "#32", "#33", "#44", "rc.2", "rc.1"),
            "windows-agent/README.md": ("#32", "rc.2", "rc.1"),
            "docs/release/QUICK-START.md": ("#32", "rc.2", "rc.1"),
            "docs/release/RC-ACCEPTANCE.md": ("rc.2", "rc.1"),
        }
        for name, terms in required.items():
            with self.subTest(document=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                for term in terms:
                    self.assertIn(term, content, (name, term))
        install = (ROOT / "INSTALLATION.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("fresh-install race", install)
        self.assertIn("Known issues in the published rc.1", security)
        self.assertIn("do not include the later security fixes", security)
        self.assertIn("do not enable power control", security.lower())

    def test_current_rc_candidate_versions_and_publication_separation(self):
        """Future RCs are version coherent but never imply publication."""
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        if manifest["release_stage"] != f"rc-candidate-v{version}" and "linux_installer" not in manifest:
            self.skipTest("only applies to unannounced RC source candidates or neutral release docs")
        candidate_url = ("https://github.com/ldeora/SmartThingsEdgeDrivers/"
                         f"releases/tag/computer-host-lan-v{version}")
        self.assertEqual(manifest["release_candidate_tag"], f"computer-host-lan-v{version}")
        if manifest["release_stage"] == f"rc-candidate-v{version}":
            self.assertNotEqual(manifest.get("github_prerelease"), candidate_url,
                                "unpublished candidate must not replace latest published URL")
        notes = (ROOT / release_notes(version)).read_text(encoding="utf-8")
        self.assertIn(candidate_url, notes)
        if "linux_installer" not in manifest:
            self.assertIn("NOT published", notes)
            self.assertIn("evidence that the release exists", notes)
        self.assertIn("separate", notes.lower())
        for field in ("agent", "edge_driver", "windows_agent"):
            self.assertIn(manifest[field], notes, field)

        if "linux_installer" in manifest:
            # Publication is external to the exact candidate bytes. A
            # versioned guide may link a release but must not claim either
            # publication or non-publication, or redirect to an older kit.
            for name in ("README.md", "INSTALLATION.md", "windows-agent/README.md",
                         "docs/release/LINUX-INSTALLER-QUICK-START.md",
                         "docs/release/WINDOWS-QUICK-START.md", "docs/release/UPGRADE.md",
                         "docs/release/TROUBLESHOOTING.md", release_notes(version)):
                content = (ROOT / name).read_text(encoding="utf-8")
                with self.subTest(document=name):
                    self.assertIn(version, "\n".join(content.splitlines()[:10]))
                    self.assertNotRegex(content.lower(),
                                        r"not (?:yet )?published|not published yet|planned rc\.3|once rc\.3 is published|latest published prerelease:.*rc\.2")
            self.assertIn(candidate_url, (ROOT / "README.md").read_text())
            self.assertIn(candidate_url, (ROOT / "docs/release/LINUX-INSTALLER-QUICK-START.md").read_text())
            self.assertIn(candidate_url, (ROOT / "docs/release/WINDOWS-QUICK-START.md").read_text())
        else:
            for name in ("README.md", "INSTALLATION.md",
                         "windows-agent/README.md", "docs/release/QUICK-START.md"):
                intro = (ROOT / name).read_text(encoding="utf-8").splitlines()[:8]
                self.assertRegex("\n".join(intro).lower(), r"(?:not published|unpublished|not a published download)", name)
                self.assertIn(version, "\n".join(intro), name)
        acceptance = (ROOT / "docs/release/RC-ACCEPTANCE.md").read_text(encoding="utf-8")
        self.assertIn(version, acceptance)
        self.assertIn("not", acceptance.lower())
        self.assertEqual(manifest["agent_protocol"], 2)
        self.assertEqual(manifest["power_control_default"], "disabled")

    def test_published_rc2_docs_link_release_and_keep_channel_distinct(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        if manifest["release_stage"] != "rc-published-v1.0.0-rc.2":
            self.skipTest("specific to published rc.2")
        url = "https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2"
        self.assertEqual(manifest["github_prerelease"], url)
        for name in ("README.md", "INSTALLATION.md", "SECURITY.md",
                     "windows-agent/README.md", "windows-agent/installer/README.md",
                     "docs/release/QUICK-START.md", "docs/release/RC-ACCEPTANCE.md",
                     "docs/release/RELEASE-NOTES-v1.0.0-rc.2.md",
                     "docs/beta/SMARTTHINGS-CHANNEL.md", "RELEASE-READINESS.md"):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(url, content, name)
            opening = "\\n".join(content.splitlines()[:8]).lower()
            self.assertNotIn("not published", opening, name)
            self.assertNotIn("unpublished rc.2", opening, name)
        self.assertIn("not independently confirmed",
                      (ROOT / "docs/beta/SMARTTHINGS-CHANNEL.md").read_text())
        self.assertEqual(manifest["power_control_default"], "disabled")

    def test_release_docs_consistent(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        for name in ("README.md", "CHANGELOG.md", "INSTALLATION.md"):
            self.assertIn(version, (ROOT / name).read_text(encoding="utf-8"), name)
        self.assertTrue((ROOT / release_notes(version)).is_file(), release_notes(version))


if __name__ == "__main__":
    unittest.main()
