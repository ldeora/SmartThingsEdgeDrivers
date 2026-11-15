"""Verify that release bundles can be built safely and without developer files."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetTests(unittest.TestCase):
    def test_build_agent_and_repo_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            p = subprocess.run([sys.executable, str(ROOT / 'scripts/ci/build_release.py'),
                                '--output-dir', str(out)], capture_output=True,
                               text=True, timeout=45)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            agent = out / 'linux-host-agent-bundle-v0.3.1-beta.1.zip'
            archive = out / 'linux-host-agent-bundle-v0.3.1-beta.1.tar.gz'
            repo = out / 'linux-host-lan-github-ready-v0.3.1-beta.1.zip'
            for path in (agent, archive, repo):
                self.assertTrue(path.exists())
            with zipfile.ZipFile(agent) as z:
                self.assertIsNone(z.testzip())
                names = z.namelist()
                self.assertTrue(all(x.startswith('linux-host-agent-bundle-v0.3.1-beta.1/') for x in names))
                self.assertTrue(any(x.endswith('/scripts/install-agent.sh') for x in names))
                self.assertTrue(any(x.endswith('/agent/linux_host_agent.py') for x in names))
                self.assertTrue(any(x.endswith('/LICENSE') for x in names))
                self.assertIn(b'Apache License', z.read('linux-host-agent-bundle-v0.3.1-beta.1/LICENSE'))
                self.assertFalse(any('/edge-driver/' in x or '/tests/' in x for x in names))
                self.assertFalse(any(x.endswith('/control-token') for x in names))
            with tarfile.open(archive, 'r:gz') as z:
                self.assertTrue(all(x.isfile() and not x.issym() for x in z.getmembers()))
                self.assertTrue(any(x.name.endswith('/INSTALLATION.md') for x in z))
                self.assertTrue(any(x.name.endswith('/LICENSE') for x in z))
            with zipfile.ZipFile(repo) as z:
                names = z.namelist()
                self.assertTrue(all(x.startswith('linux-host-lan/') for x in names))
                self.assertTrue(any(x.endswith('/edge-driver/config.yaml') for x in names))
                self.assertTrue(any(x.endswith('/tests/test_agent.py') for x in names))
                self.assertTrue(any(x.endswith('/LICENSE') for x in names))
            checksums = (out / 'SHA256SUMS.txt').read_text()
            for path in (agent, archive, repo):
                self.assertIn(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}", checksums)

    def test_license_is_complete_and_declared(self):
        license_text = (ROOT / 'LICENSE').read_text()
        self.assertIn('Apache License', license_text)
        self.assertIn('Version 2.0, January 2004', license_text)
        self.assertIn('END OF TERMS AND CONDITIONS', license_text)
        self.assertIn('APPENDIX: How to apply the Apache License', license_text)
        import json
        release = json.loads((ROOT / 'release.json').read_text())
        self.assertEqual(release['redistribution_license'], 'Apache-2.0')

    def test_sensitive_local_files_excluded_and_ignored(self):
        ignore = (ROOT / '.gitignore').read_text()
        for filename in ('control-token', 'installation-id', '*.pem', '*.key'):
            self.assertIn(filename, ignore)
        builder = (ROOT / 'scripts/ci/build_release.py').read_text()
        self.assertIn('OMIT_NAMES', builder)
        self.assertIn('OMIT_SUFFIXES', builder)
        self.assertIn('AGENT_SCRIPTS', builder)


if __name__ == '__main__':
    unittest.main()
