"""Release-version and install/upgrade consistency checks (beta, RC, stable)."""
from pathlib import Path
import json
import re
import tempfile
import unittest
from zipfile import ZipFile

from scripts.ci.build_windows_kit import build, release_kind
from scripts.ci.user_docs import USER_DOCS, notes_path as release_notes

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-(?:beta|rc)\.\d+)?$")


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

    def test_packaged_user_guides_reference_current_version(self):
        """Check current download instructions at every release stage.

        Historical tag-pinned reference links are allowed; current release
        download links and installer filenames must match the manifest exactly.
        """
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        tag = f"computer-host-lan-v{version}"
        release_url = (
            "https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/" + tag
        )
        required = {
            "SECURITY.md", "docs/install-linux.md",
            "docs/install-windows.md", "docs/testing.md",
        }
        self.assertTrue(required.issubset(USER_DOCS))
        # Capture the complete tag, not a substring: stable 1.0.0 must not
        # accept 1.0.0-rc.3, nor rc.1 accidentally accept rc.10.
        release_links = re.compile(
            r"https://github\.com/ldeora/SmartThingsEdgeDrivers/"
            r"releases/(?:tag|download)/(computer-host-lan-v[^\s/)\x60>]+)"
        )
        asset_names = re.compile(
            r"computer-host-lan-v([\w.-]+?)-"
            r"(?:linux-x64-unsigned-installer|windows-x64-unsigned-setup\.exe)"
        )
        for name in ("README.md", *USER_DOCS):
            if not name.endswith(".md"):
                continue
            with self.subTest(document=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                tags = release_links.findall(content)
                if name in required or name == "README.md":
                    self.assertIn(tag, tags, release_url)
                for found in tags:
                    self.assertEqual(found, tag, "stale release download link")
                for found in asset_names.findall(content):
                    self.assertEqual(found, version, "stale installer filename")
        for name, suffix in (
            ("docs/install-linux.md", "linux-x64-unsigned-installer"),
            ("docs/install-windows.md", "windows-x64-unsigned-setup.exe"),
        ):
            self.assertIn(f"{tag}-{suffix}",
                          (ROOT / name).read_text(encoding="utf-8"), name)

    def test_published_docs_reference_current_release(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        if manifest["release_stage"] != f"{release_kind(version)}-published-v{version}":
            self.skipTest("release is not yet published")
        release_url = manifest.get("github_release", manifest.get("github_prerelease"))
        for name in ("README.md", "SECURITY.md", "docs/install-linux.md",
                     "docs/install-windows.md", "docs/testing.md", release_notes(version)):
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
                    quick = ROOT / "docs/install-windows.md"
                    self.assertEqual(zip_file.read("docs/install-windows.md"), quick.read_bytes())
                    self.assertIn(b"(install-windows.md)", zip_file.read("docs/START-HERE.md"))
                    self.assertEqual(zip_file.read("docs/testing.md"),
                                     (ROOT / "docs/testing.md").read_bytes())
                    self.assertIn(b"(testing.md)", zip_file.read("docs/TEST-CHECKLIST.md"))
                    # Every relative screenshot in the guide is present and
                    # checksummed, not merely linked in the repository.
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
                    for name in ("SECURITY.md", "docs/smartthings.md", "docs/upgrade.md",
                                 "docs/troubleshooting.md", "docs/install-linux.md",
                                 "docs/THIRD-PARTY-NOTICES.md", "LICENSE"):
                        self.assertEqual(zip_file.read(name), (ROOT / name).read_bytes())
                    self.assertNotIn("docs/release/RC3-READINESS.md", zip_file.namelist())

    def test_published_rc1_security_warning_retained(self):
        """Old downloadable rc.1 lacks security fixes; keep the warning."""
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        for term in ("#30", "#31", "#32", "#33", "#44", "rc.2", "rc.1",
                     "Known issues in the published rc.1",
                     "do not include the later security fixes",
                     "cannot eliminate the fresh-creation race"):
            self.assertIn(term, security)
        self.assertIn("do not enable power control", security.lower())

    def test_current_notes_and_publication_separation(self):
        """Build identity is independent of the last verified public assets."""
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        tag = f"computer-host-lan-v{version}"
        kind = release_kind(version)
        url = f"https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/{tag}"
        self.assertEqual(manifest["release_candidate_tag"], tag)
        notes = (ROOT / release_notes(version)).read_text(encoding="utf-8")
        self.assertIn(url, notes)
        self.assertIn("separate", notes.lower())
        for field in ("agent", "edge_driver", "windows_agent"):
            self.assertIn(manifest[field], notes, field)
        published = manifest["last_published"]
        self.assertRegex(published["source_commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(published["manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(published["published_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(published["url"],
                         "https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/"
                         + published["tag"])
        if manifest["release_stage"] == f"{kind}-published-v{version}":
            self.assertEqual(published["tag"], tag)
            self.assertEqual(published["url"], url)
            self.assertEqual(manifest.get("github_release", manifest.get("github_prerelease")), url)
        else:
            self.assertNotEqual(published["tag"], tag,
                                "candidate is not its own publication")
            self.assertNotEqual(manifest.get("github_release", manifest.get("github_prerelease")), url)
        self.assertIn("issues/119", manifest["candidate_acceptance"])
        self.assertEqual(manifest["agent_protocol"], 2)
        self.assertEqual(manifest["power_control_default"], "disabled")

    def test_release_docs_consistent(self):
        manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
        version = manifest["integration"]
        for name in ("README.md", "CHANGELOG.md", release_notes(version)):
            self.assertIn(version, (ROOT / name).read_text(encoding="utf-8"), name)
        self.assertTrue((ROOT / release_notes(version)).is_file(), release_notes(version))


if __name__ == "__main__":
    unittest.main()
