"""No-root checks for source provenance and interpreter selection."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / 'scripts/python-selector.sh'


class PortabilityTests(unittest.TestCase):
    def _fake_python(self, directory, name, exit_code):
        target = Path(directory) / name
        target.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then exit ' + str(exit_code) + '; fi\nexit 0\n')
        target.chmod(0o755)
        return str(target)

    def _select(self, env_path, explicit=''):
        # Path is sourced by a fresh shell; no modifications to the host OS.
        expr = f'. "{SELECTOR}"; linuxhost_select_python "{explicit}" && printf "%s" "$LINUXHOST_PYTHON"'
        env = os.environ.copy()
        env['PATH'] = env_path
        return subprocess.run(['/bin/sh', '-c', expr], env=env,
                              capture_output=True, text=True)

    def test_python_selector_rejects_pre310_and_finds_parallel_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._fake_python(tmp, 'python3', 1)   # simulate default Python 3.9
            newer = self._fake_python(tmp, 'python3.11', 0)
            p = self._select(tmp)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout, newer)

    def test_python_selector_reports_missing_compatible_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._fake_python(tmp, 'python3', 1)
            p = self._select(tmp)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('Python 3.10 or newer', p.stderr)

    def test_python_override_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._fake_python(tmp, 'python3.12', 0)
            self.assertEqual(self._select(tmp, target).stdout, target)
            self.assertNotEqual(self._select(tmp, 'python3.12').returncode, 0)
            self.assertNotEqual(self._select(tmp, '/tmp/path with spaces').returncode, 0)

    def test_live_source_does_not_include_private_host_fixtures(self):
        production = list((ROOT/'agent').rglob('*.py')) + list((ROOT/'scripts').glob('*.sh')) + \
                     list((ROOT/'edge-driver/src').rglob('*.lua'))
        # The distributed runtime must not assume a particular user, NIC,
        # private IP, site-specific Linux hostname or hardware address.
        forbidden = ('/home/', '192.168.1.', 'my-laptop.local',
                     'MY_PC_NAME', 'HOST_MAC_OVERRIDE=')
        for p in production:
            content = p.read_text().lower()
            for value in forbidden:
                with self.subTest(file=p.name, value=value):
                    self.assertNotIn(value, content)

    def test_installer_checks_compatible_python_before_mutating_files(self):
        s = (ROOT/'scripts/install-agent.sh').read_text()
        self.assertIn('linuxhost_select_python', s)
        self.assertIn('PYTHON_BIN=$LINUXHOST_PYTHON', s)
        self.assertIn('install_core.py', s)
        self.assertLess(s.index('linuxhost_select_python'), s.index('useradd --system'))
        self.assertIn('--python', s)
        self.assertNotIn('update-alternatives', s)

    def test_linux_state_preserves_conservative_failure_inference(self):
        # The shared reducer is deliberately extended for short Windows/Linux
        # suspend/resume and cancelled-shutdown behavior. A byte-identical
        # Linux-only v0.3.1 SHA check would prohibit any tested bug fix.
        # Behavioral transitions remain covered by test_lua_state.py.
        source = (ROOT / 'edge-driver/src/computerhost/state.lua').read_text()
        for invariant in ('function M.failure(', 'kind=="agent_unavailable"',
                          'kind=="host_unreachable"', 'host_failures>=threshold',
                          'if action=="reboot"', 'return "unknown",nil,false'):
            self.assertIn(invariant, source)
        self.assertIn('function M.success(action,boot_changed,failed_polls,elapsed_seconds)', source)



if __name__ == '__main__':
    unittest.main()
