"""Beta release engineering checks. No host mutation, no external services."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BASELINE_AGENT_SHA256 = '58d687b0f2223f849e3e76c0d1f28f3bdd3743cf9c214443a695d0286a0e4aa7'
BASELINE_EDGE_HASHES = '25cd24f6ff0914fa05657a2dbeb4cd00004047fc41998493313366525131a77b'


class BetaReadiness(unittest.TestCase):
    def test_release_manifest_pins_unchanged_runtime(self):
        release = json.loads((ROOT / 'release.json').read_text())
        self.assertEqual(release['integration'], '0.3.1-beta.1')
        self.assertEqual(release['agent'], '0.3.0')
        self.assertEqual(release['edge_driver'], '0.2.9')
        self.assertEqual(release['power_control_default'], 'disabled')
        self.assertEqual(release['redistribution_license'], 'Apache-2.0')

    def test_agent_source_frozen(self):
        digest = hashlib.sha256((ROOT / 'agent/linux_host_agent.py').read_bytes()).hexdigest()
        self.assertEqual(digest, BASELINE_AGENT_SHA256)

    def test_edge_driver_source_frozen(self):
        root = ROOT / 'edge-driver'
        entries = sorted(str(path.relative_to(root)) + ':' + hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in root.rglob('*') if path.is_file())
        digest = hashlib.sha256(('\n'.join(entries) + '\n').encode()).hexdigest()
        self.assertEqual(digest, BASELINE_EDGE_HASHES)

    def test_machine_specific_values_absent_from_production(self):
        prohibited = (b'/home/example-user/', b'192.0.2.123', b'02:11:22:33:44:55',
                      b'example-nic0', b'00000000-1111-2222-3333-444444444444')
        for folder in ('agent', 'scripts', 'edge-driver/src'):
            for file in (ROOT / folder).rglob('*'):
                if file.is_file() and file.suffix in ('.py', '.sh', '.lua', '.service'):
                    with self.subTest(file=file):
                        content = file.read_bytes().lower()
                        for string in prohibited:
                            self.assertNotIn(string, content)

    def test_beta_report_is_read_only_and_redacted(self):
        script = (ROOT / 'scripts/beta-report.sh').read_text()
        self.assertNotIn('control-token', script)
        self.assertNotIn('installation-id', script)
        self.assertNotIn('journalctl', script)
        self.assertIn('127.0.0.1', script)
        p = subprocess.run(['/bin/sh', str(ROOT / 'scripts/beta-report.sh')],
                           capture_output=True, text=True, timeout=12)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('beta report', p.stdout)
        self.assertNotIn('wol_mac', p.stdout)
        self.assertNotIn('control-token', p.stdout)
        self.assertNotIn('installation-id', p.stdout)

    def test_workflow_has_staged_distribution_matrix(self):
        workflow = (ROOT / 'ci/github-actions-template.yml').read_text()
        for image in ('debian:12', 'debian:13', 'ubuntu:24.04', 'ubuntu:26.04',
                      'fedora:43', 'fedora:44'):
            self.assertIn(image, workflow)
        self.assertIn('run-container-tests.sh', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('do NOT run systemd as PID 1', workflow)

    def test_tester_docs_present(self):
        for name in ('START-HERE', 'TESTER-CHECKLIST', 'FEEDBACK-AND-SUPPORT',
                     'COMPATIBILITY-STATUS', 'SECURITY-AND-PRIVACY',
                     'PACKAGING-RELEASE-DECISION', 'PUBLICATION-GATES', 'LICENSE-DECISION'):
            self.assertGreater((ROOT / 'docs/beta' / (name + '.md')).stat().st_size, 500)

    def test_no_user_data_files_in_source_tree(self):
        files = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()]
        self.assertFalse(any(p.endswith('/control-token') or p.endswith('/installation-id') for p in files))


if __name__ == '__main__':
    unittest.main()
