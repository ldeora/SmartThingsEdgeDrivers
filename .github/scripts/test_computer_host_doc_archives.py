"""Verify the actual generated user archives, not just repository links."""
from pathlib import Path
import subprocess
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
            self.assertFalse(archive_links(docs, strip_root=True), archive_links(docs, strip_root=True))
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

    def test_missing_packaged_image_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.zip"
            with ZipFile(path, "w") as archive:
                archive.writestr("docs/guide.md", "![missing](image.png)")
            self.assertEqual(sum(archive_links(path).values()), 1)


if __name__ == "__main__":
    unittest.main()
