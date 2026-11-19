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
    def test_dev_release_manifest_and_power_default(self):
        release = json.loads((ROOT / 'release.json').read_text())
        self.assertRegex(release['integration'], r'^\d+\.\d+\.\d+-beta\.\d+$')
        self.assertEqual(release['agent'], '0.4.2-beta.1')
        self.assertEqual(release['edge_driver'], '0.4.2-beta.1')
        self.assertRegex(release['windows_agent'], r'^\d+\.\d+\.\d+-beta\.\d+$')
        self.assertEqual(release['agent_protocol'], 2)
        self.assertEqual(release['power_control_default'], 'disabled')

    def test_linux_runtime_invariants_preserved(self):
        agent = (ROOT / 'agent/linux_host_agent.py').read_text()
        driver = (ROOT / 'edge-driver/src/init.lua').read_text()
        for item in ('BoundedHTTPServer', 'ChallengeRateLimiter',
                     'MAX_CONCURRENT_CLIENTS', 'request_power',
                     'ALLOWED_ACTIONS', 'HeaderBudgetReader'):
            self.assertIn(item, agent)
        for item in ('State.failure', 'State.success', 'Power.wake',
                     'Power.action', 'Telemetry.metrics', 'Presence.classify_failure'):
            self.assertIn(item, driver)
        self.assertIn('User=linuxhost',
                      (ROOT / 'agent/systemd/linux-host-agent.service').read_text())

    def test_machine_specific_values_absent_from_production(self):
        prohibited = (b'aroedl', b'192.168.1.123', b'6c:4b:90:9f:32:dd',
                      b'enp1s0f0', b'b9024f22-4e09-4413-9c36-3d7b75563051')
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
        workflow = (ROOT.parent / '.github/workflows/computer-host-linux.yml').read_text() if (ROOT.parent / '.github/workflows/computer-host-linux.yml').exists() else ''
        if not workflow:
            self.skipTest('Active workflow resides at monorepo root, omitted in standalone source archive')
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

    def test_wol_logs_do_not_expose_raw_mac_or_ip(self):
        power = (ROOT / 'edge-driver/src/computerhost/power.lua').read_text()
        discovery = (ROOT / 'edge-driver/src/computerhost/discovery.lua').read_text()
        self.assertNotIn('MAC %s, broadcast %s', power)
        self.assertNotIn('info.id,c.host,c.port', discovery)
        self.assertNotIn('..new_mac)', discovery)

    def test_windows_package_contains_dependency_notice(self):
        source = (ROOT / 'scripts/ci/build_windows_kit.py').read_text()
        setup = (ROOT / 'windows-agent/installer/ComputerHostLAN.iss').read_text()
        self.assertIn('THIRD-PARTY-NOTICES.md', source)
        self.assertIn('THIRD-PARTY-NOTICES.md', setup)
        self.assertIn('Zeroconf', (ROOT / 'docs/beta/THIRD-PARTY-NOTICES.md').read_text())


if __name__ == '__main__':
    unittest.main()
