"""Private-state candidate fixtures; no real account or agent operations."""
from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_core as core
import retained_state_eligibility as adoption

IDENTITY = 'abcd1234-1234-4abc-8abc-123456789abc'
KEY = 'a9' * 32


class RetainedStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.uid = os.geteuid()
        self.gid = os.getegid()
        self.state = self.root / 'var/lib/linux-host-agent'
        self.state.mkdir(parents=True, mode=0o700)
        self.state.chmod(0o700)
        self.identity = self.state / 'installation-id'
        self.key = self.state / 'control-token'
        self.identity.write_text(IDENTITY + '\n')
        self.key.write_text(KEY + '\n')
        for path in (self.identity, self.key):
            path.chmod(0o600)
        # Fixture ownership uses the test runner. Test the non-root account
        # policy separately, without needing chown or a real linuxhost user.
        patch = mock.patch.object(adoption, '_account', return_value=(self.uid, self.gid))
        self.account = patch.start()
        self.addCleanup(patch.stop)

    def inspect(self):
        return adoption.inspect_retained_state(self.root, owner_uid=self.uid)

    def test_candidate_contains_no_private_values_or_digests(self):
        before = {p.name: p.read_bytes() for p in self.state.iterdir()}
        result = self.inspect()
        self.assertEqual(result.status, 'candidate')
        self.assertFalse(result.secrets_included)
        for field in ('protocol_provenance', 'service_state', 'journal_state'):
            self.assertEqual(getattr(result, field), 'not_verified')
        self.assertNotIn(IDENTITY, repr(asdict(result)))
        self.assertNotIn(KEY, repr(asdict(result)))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.state.iterdir()})

    def test_conflicting_managed_file_and_partial_owner_directory_refused(self):
        for name in (core.APP_FILES[0], core.OWNER_DIR):
            path = self.root / name.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == core.OWNER_DIR:
                path.mkdir()
            else:
                path.write_text('ambiguous')
            with self.assertRaisesRegex(adoption.AdoptionEligibilityError, 'conflicting'):
                self.inspect()
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()

    def test_missing_extra_and_linked_private_entries_refused(self):
        extra = self.state / '.interrupted.tmp'
        extra.write_text('fixture')
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        extra.unlink()
        self.key.unlink()
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        target = self.root / 'key'
        target.write_text(KEY + '\n')
        self.key.symlink_to(target)
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        self.key.unlink()
        target.chmod(0o600)
        os.link(target, self.key)
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()

    def test_invalid_format_and_mode_are_not_repaired(self):
        self.identity.write_text('x' * 36 + '\n')
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        self.assertEqual(self.identity.read_text(), 'x' * 36 + '\n')
        self.identity.write_text(IDENTITY + '\n')
        self.key.chmod(0o644)
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        self.key.chmod(0o600)
        self.key.write_text('Z' * 64 + '\n')
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        self.assertEqual(self.key.read_text(), 'Z' * 64 + '\n')

    def test_wrong_account_owner_and_writable_parent_refused(self):
        self.account.return_value = (self.uid + 1, self.gid)
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()
        self.account.return_value = (self.uid, self.gid)
        self.state.parent.chmod(0o777)
        with self.assertRaises(adoption.AdoptionEligibilityError):
            self.inspect()



class AccountPolicyTests(unittest.TestCase):
    def test_account_policy(self):
        valid = dict(pw_name='linuxhost', pw_uid=123, pw_gid=124,
                     pw_dir='/var/lib/linux-host-agent', pw_shell='/sbin/nologin')
        group = SimpleNamespace(gr_name='linuxhost', gr_gid=124)
        with mock.patch.object(adoption.grp, 'getgrnam', return_value=group):
            for updates in ({}, {'pw_uid': 0}, {'pw_gid': 0}, {'pw_gid': 125},
                            {'pw_dir': '/root'}, {'pw_shell': '/bin/bash'}):
                with self.subTest(updates=updates), mock.patch.object(
                        adoption.pwd, 'getpwnam',
                        return_value=SimpleNamespace(**dict(valid, **updates))):
                    if updates:
                        with self.assertRaises(adoption.AdoptionEligibilityError):
                            adoption._account()
                    else:
                        self.assertEqual(adoption._account(), (123, 124))
            with mock.patch.object(adoption.pwd, 'getpwnam', side_effect=KeyError):
                with self.assertRaisesRegex(adoption.AdoptionEligibilityError, 'account_unavailable'):
                    adoption._account()


if __name__ == '__main__':
    unittest.main()
