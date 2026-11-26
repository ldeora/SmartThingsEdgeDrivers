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


class LinuxReleaseTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        from scripts.ci.linux_release_metadata import asset_name
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.commit = "a" * 40
        self.manifest = {
            "integration": "1.0.0-rc.3", "agent": "0.4.7-rc.3",
            "edge_driver": "0.4.7-rc.3", "windows_agent": "0.2.8-rc.3",
            "agent_protocol": 2,
            "linux_installer": {
                "runtime": "linux-amd64", "go_version": "1.25.14",
                "unsigned": True, "reproducible_build_required": True,
            },
        }
        self.name = asset_name(self.manifest)
        self.a, self.b, self.out = (self.root / p for p in ("a", "b", "out"))
        data = b"fixture not an executable"
        digest = hashlib.sha256(data).hexdigest()
        info = "installer: go1.25.14\n" + "".join(
            f"\tbuild\t{k}={v}\n" for k, v in (
                ("GOOS", "linux"), ("GOARCH", "amd64"), ("GOAMD64", "v1"),
                ("CGO_ENABLED", "0"), ("-trimpath", "true"), ("vcs", "git"),
                ("vcs.revision", self.commit), ("vcs.modified", "false")))
        for folder in (self.a, self.b):
            folder.mkdir()
            (folder / self.name).write_bytes(data)
            (folder / f"{self.name}.sha256").write_text(f"{digest}  {self.name}\n")
            (folder / "go-build-info.txt").write_text(info)

    def assemble(self):
        from scripts.ci.linux_release_metadata import assemble
        assemble(self.a, self.b, self.out, self.manifest, self.commit)

    def test_equal_replicas_and_metadata(self):
        from scripts.ci.linux_release_metadata import validate_metadata
        self.assemble()
        validate_metadata(self.out, self.manifest, self.commit)
        self.assertEqual((self.out / self.name).read_bytes(),
                         (self.a / self.name).read_bytes())

    def test_reject_different_replicas(self):
        (self.b / self.name).write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "replicas differ"):
            self.assemble()
        self.assertFalse(self.out.exists())

    def test_reject_wrong_source_and_toolchain(self):
        for folder in (self.a, self.b):
            path = folder / "go-build-info.txt"
            path.write_text(path.read_text().replace(self.commit, "b" * 40))
        with self.assertRaisesRegex(ValueError, "vcs.revision"):
            self.assemble()

    def test_reject_dirty_build(self):
        for folder in (self.a, self.b):
            path = folder / "go-build-info.txt"
            path.write_text(path.read_text().replace("modified=false", "modified=true"))
        with self.assertRaisesRegex(ValueError, "vcs.modified"):
            self.assemble()

    def test_reject_modified_asset_and_metadata(self):
        from scripts.ci.linux_release_metadata import validate_metadata
        self.assemble()
        path = self.out / f"{self.name}.build-info.json"
        original = json.loads(path.read_text())
        for field, value in (("agent", "old"), ("source_commit", "b" * 40),
                             ("unsigned", False), ("reproducible", False),
                             ("attested", True), ("sha256", "0" * 64)):
            with self.subTest(field=field):
                path.write_text(json.dumps({**original, field: value}))
                with self.assertRaisesRegex(ValueError, field):
                    validate_metadata(self.out, self.manifest, self.commit)
        path.write_text(json.dumps(original))
        (self.out / self.name).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            validate_metadata(self.out, self.manifest, self.commit)


if __name__ == "__main__":
    unittest.main()
