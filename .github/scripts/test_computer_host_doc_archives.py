"""Verify the actual generated user archives, not just repository links."""
from pathlib import Path
import subprocess
import hashlib
import json
import sys
import tempfile
import unittest
from zipfile import ZipFile

from check_computer_host_docs import check

ROOT = Path(__file__).resolve().parents[2] / "computer-host-lan"


def archive_links(path, strip_root=False):
    with ZipFile(path) as archive:
        members = {n for n in archive.namelist() if not n.endswith("/")}
        if strip_root:
            roots = {n.split("/", 1)[0] for n in members}
            if len(roots) != 1 or any("/" not in n for n in members):
                raise AssertionError("Expected exactly one archive root")
            prefix = roots.pop() + "/"
        else:
            prefix = ""
        paths = {n[len(prefix):] for n in members}
        return check(paths, lambda p: archive.read(prefix + p).decode("utf-8"),
                     scope=lambda p: p.endswith(".md"))


class ArchiveLinks(unittest.TestCase):
    def test_user_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            subprocess.run([sys.executable, str(ROOT / "scripts/ci/build_release.py"),
                            "--output-dir", str(tmp)], check=True)
            docs = next(tmp.glob("*-documentation.zip"))
            defects = archive_links(docs, strip_root=True)
            self.assertFalse(defects, defects)
            source = next(tmp.glob("*-source.zip"))
            defects = archive_links(source, strip_root=True)
            self.assertFalse(defects, defects)
            manifest = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
            version = manifest["integration"]
            sys.path.insert(0, str(ROOT))
            try:
                from scripts.ci.user_docs import USER_DOCS, docs_paths, notes_path
            finally:
                sys.path.pop(0)
            with ZipFile(docs) as archive:
                prefix = f"computer-host-lan-docs-v{version}/"
                expected = set(docs_paths(version))
                self.assertEqual(set(archive.namelist()),
                                 {prefix + name for name in expected | {"FILES.sha256"}})
                for name in expected:
                    data = archive.read(prefix + name)
                    self.assertEqual(data, (ROOT / name).read_bytes(), name)
                    digest = hashlib.sha256(data).hexdigest()
                    self.assertIn(f"{digest}  {name}\n",
                                  archive.read(prefix + "FILES.sha256").decode("utf-8"))
            with ZipFile(source) as archive:
                prefix = f"computer-host-lan-v{version}/"
                for name in expected:
                    self.assertEqual(archive.read(prefix + name),
                                     (ROOT / name).read_bytes(), name)
            publish = tmp / "publish"
            publish.mkdir()
            (publish / "ComputerHost.WindowsAgent.exe").write_bytes(b"fixture")
            (publish / "appsettings.json").write_text("{}")
            subprocess.run([sys.executable, str(ROOT / "scripts/ci/build_windows_kit.py"),
                            "--published-dir", str(publish), "--output-dir", str(tmp),
                            "--source-commit", "a" * 40], check=True)
            win = next(tmp.glob("*-windows-x64-unsigned.zip"))
            defects = archive_links(win)
            self.assertFalse(defects, defects)
            with ZipFile(win) as archive:
                sums = archive.read("FILES.sha256").decode("utf-8")
                for name in (*USER_DOCS, "LICENSE", "CHANGELOG.md"):
                    data = archive.read(name)
                    self.assertEqual(data, (ROOT / name).read_bytes(), name)
                    self.assertIn(f"{hashlib.sha256(data).hexdigest()}  {name}\n", sums)
                self.assertEqual(archive.read("docs/RELEASE-NOTES.md"),
                                 (ROOT / notes_path(version)).read_bytes())
                for name in archive.namelist():
                    self.assertFalse(name.startswith(("docs/development/", "docs/history/",
                                                      "docs/beta/", "docs/reference/")), name)

    def test_missing_packaged_image_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("docs/guide.md", "![missing](image.png)")
            self.assertEqual(sum(archive_links(path).values()), 1)


if __name__ == "__main__":
    unittest.main()
