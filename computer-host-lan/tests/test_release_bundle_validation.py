"""Check source-commit and component-version validation for release bundles."""
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.ci.verify_release_bundle import validate_bundle


class VersionedBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.commit = "a" * 40
        self.manifest = {
            "integration": "0.5.5-beta.1",
            "windows_agent": "0.2.4-beta.1",
            "agent": "0.4.3-beta.1",
            "edge_driver": "0.4.3-beta.1",
        }
        name = "computer-host-lan-v0.5.5-beta.1"
        self.windows = self.path / f"{name}-windows-x64-unsigned.zip"
        self.source = self.path / f"{name}-source.zip"
        self.docs = self.path / f"{name}-documentation.zip"
        (self.path / f"{name}-windows-x64-unsigned-setup.exe").write_bytes(b"stub")
        with ZipFile(self.windows, "w") as z:
            z.writestr("BUILD-INFO.json", json.dumps({
                "integration": self.manifest["integration"],
                "windows_agent": self.manifest["windows_agent"],
                "runtime": "win-x64", "source_commit": self.commit,
                "unsigned": True,
            }))
        with ZipFile(self.source, "w") as z:
            z.writestr(f"{name}/release.json", json.dumps(self.manifest))
        with ZipFile(self.docs, "w") as z:
            z.writestr("computer-host-lan-docs-v0.5.5-beta.1/release.json", json.dumps(self.manifest))

    def test_consistent_bundle(self):
        validate_bundle(self.path, self.manifest, self.commit)

    def test_rejects_wrong_commit_even_if_zips_integrity_is_valid(self):
        with self.assertRaisesRegex(ValueError, "source_commit mismatch"):
            validate_bundle(self.path, self.manifest, "b" * 40)

    def test_rejects_wrong_agent_version_even_if_checksum_valid(self):
        m = dict(self.manifest)
        m["windows_agent"] = "0.2.3-beta.1"
        with self.assertRaisesRegex(ValueError, "windows_agent mismatch"):
            validate_bundle(self.path, m, self.commit)

    def test_rejects_wrong_archive_name(self):
        self.docs.rename(self.path / "incorrect-documentation.zip")
        with self.assertRaisesRegex(ValueError, "wrong versioned ZIP set"):
            validate_bundle(self.path, self.manifest, self.commit)

    def test_rejects_wrong_source_manifest(self):
        m = dict(self.manifest)
        m["edge_driver"] = "0.4.4-beta.1"
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            validate_bundle(self.path, m, self.commit)


if __name__ == "__main__":
    unittest.main()
