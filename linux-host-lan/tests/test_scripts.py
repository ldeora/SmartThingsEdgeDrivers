"""Shell portability and dry-run guard checks (no privileged mutations)."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'

class ScriptTests(unittest.TestCase):
    def test_posix_shell_syntax(self):
        for name in ('install-agent.sh','configure-wol.sh','diagnose.sh','publish-presentations.sh','python-selector.sh','preflight.sh','rollback-agent.sh','uninstall-agent.sh'):
            with self.subTest(script=name):
                subprocess.run(['sh','-n',str(SCRIPTS/name)],check=True)

    def test_invalid_wol_args_are_rejected_before_any_change(self):
        for args in ([],['--interface','bad interface'],['--interface','eth0','--bogus']):
            result=subprocess.run(['sh',str(SCRIPTS/'configure-wol.sh'),*args],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,2)

    def _mock_wol_tools(self, directory, case):
        # Simulate ethtool netlink WOL_GET failing with EPERM but returning
        # success and incomplete stdout, exactly as seen on Gentoo.
        ethtool = Path(directory) / 'ethtool'
        ethtool.write_text("""#!/bin/sh
case "$WOL_MOCK_CASE:$1" in
  legacy_ok:--disable-netlink)
    printf 'Settings for lo:\n    Supports Wake-on: pumbg\n    Wake-on: g\n'
    exit 0 ;;
  unsupported:*)
    printf 'Settings for lo:\n    Supports Wake-on: pu\n    Wake-on: d\n'
    exit 0 ;;
  *:--disable-netlink)
    echo 'netlink error: Operation not permitted' >&2
    exit 1 ;;
  *)
    printf 'Settings for lo:\n'
    echo 'netlink error: Operation not permitted' >&2
    exit 0 ;;
esac
""")
        ethtool.chmod(0o755)
        for tool in ('systemctl', 'udevadm'):
            path = Path(directory) / tool
            path.write_text('#!/bin/sh\nexit 1\n')
            path.chmod(0o755)
        env = os.environ.copy()
        env.update(PATH=directory + os.pathsep + env.get('PATH',''), WOL_MOCK_CASE=case)
        return env

    @unittest.skipUnless(Path('/sys/class/net/lo/address').exists(), 'Linux loopback required for mock')
    def test_wol_dry_run_falls_back_from_partial_netlink_to_ioctl(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self._mock_wol_tools(temp, 'legacy_ok')
            result = subprocess.run(['sh',str(SCRIPTS/'configure-wol.sh'),'--interface','lo'],
                                    env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ethtool --disable-netlink (ioctl)',result.stdout)
            self.assertIn('Dry run',result.stdout)
            self.assertNotIn('does not advertise',result.stderr)

    @unittest.skipUnless(Path('/sys/class/net/lo/address').exists(), 'Linux loopback required for mock')
    def test_failed_wol_queries_do_not_claim_no_hardware_support(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self._mock_wol_tools(temp, 'both_fail')
            result = subprocess.run(['sh',str(SCRIPTS/'configure-wol.sh'),'--interface','lo'],
                                    env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn('not proof that WOL is unsupported',result.stderr)
            self.assertNotIn('does not advertise',result.stderr)
            self.assertIn('sudo ethtool lo',result.stderr)

    @unittest.skipUnless(Path('/sys/class/net/lo/address').exists(), 'Linux loopback required for mock')
    def test_diagnostics_report_ioctl_wol_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self._mock_wol_tools(temp,'legacy_ok')
            result = subprocess.run(['sh',str(SCRIPTS/'diagnose.sh'),'--interface','lo'],
                                    env=env,capture_output=True,text=True,check=True)
            self.assertIn('Legacy ioctl fallback',result.stdout)
            self.assertIn('Supports Wake-on: pumbg',result.stdout)
            self.assertIn('Wake-on: g',result.stdout)

    @unittest.skipUnless(Path('/sys/class/net/lo/address').exists(), 'Linux loopback required for mock')
    def test_diagnostics_distinguish_permissions_from_unsupported_hardware(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self._mock_wol_tools(temp,'both_fail')
            result = subprocess.run(['sh',str(SCRIPTS/'diagnose.sh'),'--interface','lo'],
                                    env=env,capture_output=True,text=True,check=True)
            self.assertIn('query failed or returned no WOL data',result.stdout)
            self.assertIn('This does not mean that WOL is unsupported',result.stdout)

    @unittest.skipUnless(Path('/sys/class/net/lo/address').exists(), 'Linux loopback required for mock')
    def test_genuinely_unsupported_wol_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self._mock_wol_tools(temp, 'unsupported')
            result = subprocess.run(['sh',str(SCRIPTS/'configure-wol.sh'),'--interface','lo'],
                                    env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertIn('does not advertise magic-packet WOL support',result.stderr)

    def test_installer_dry_run_never_writes(self):
        result=subprocess.run(['sh',str(SCRIPTS/'install-agent.sh'),'--dry-run'],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Dry run only',result.stdout)
        self.assertIn('[PLAN]',result.stdout)
        self.assertNotIn('Installed Linux Host Agent',result.stdout)

    def test_presentation_publication_requires_opt_in(self):
        result=subprocess.run(['sh',str(SCRIPTS/'publish-presentations.sh')],
                              capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.count('capabilities:translations:upsert'),12)
        self.assertEqual(result.stdout.count('capabilities:presentation:update'),6)
        self.assertIn('DRY RUN',result.stdout)

if __name__=='__main__':unittest.main()
