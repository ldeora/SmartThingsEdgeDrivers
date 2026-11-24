"""Metadata continuity on disposable roots; no agent or systemd operations."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import credential_continuity as c


class CredentialContinuityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.uid = os.geteuid()
        self.account = (self.uid, os.getegid())
        self.state = self.root / 'var/lib/linux-host-agent'

    def observe(self, account=True):
        return c.observe(self.root, owner_uid=self.uid,
                         account=self.account if account else None)

    def create(self, name):
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.state / name
        path.write_bytes(b'x' * 64)
        path.chmod(0o600)
        return path

    def test_retained_metadata_no_content_reads(self):
        for name in c._NAMES:
            self.create(name)
        with mock.patch.object(os, 'read', side_effect=AssertionError('content read')):
            old = self.observe()
            self.assertEqual(c.compare(old, self.observe()),
                             dict.fromkeys(c._NAMES, 'verified'))
        self.assertNotIn('credentials=', repr(old))

    def test_absence_and_new_creation(self):
        old = self.observe(account=False)
        self.assertEqual(c.compare(old, self.observe(account=False)),
                         dict.fromkeys(c._NAMES, 'absent'))
        self.create('control-token')
        now = self.observe()
        with self.assertRaises(c.ContinuityError):
            c.compare(old, now)
        self.assertEqual(c.compare(old, now, allow_new=True),
                         {'installation-id': 'absent', 'control-token': 'newly_present'})

    def test_mixed_creation_does_not_compare_directory_timestamps(self):
        self.create('installation-id')
        old = self.observe()
        self.create('control-token')
        self.assertEqual(c.compare(old, self.observe(), allow_new=True),
                         {'installation-id': 'verified', 'control-token': 'newly_present'})

    def test_rewrite_replacement_and_disappearance(self):
        path = self.create('control-token')
        old = self.observe()
        path.write_bytes(b'y' * 64)
        with self.assertRaises(c.ContinuityError):
            c.compare(old, self.observe())
        old = self.observe()
        path.rename(self.state / 'old')
        self.create('control-token')
        with self.assertRaises(c.ContinuityError):
            c.compare(old, self.observe())
        old = self.observe()
        path.unlink()
        with self.assertRaises(c.ContinuityError):
            c.compare(old, self.observe())

    def test_stable_accounted_alias_and_removal(self):
        path = self.create('installation-id')
        alias = self.state / ('.installation-id.' + 'a'*16 + '.tmp')
        os.link(path, alias)
        old = self.observe()
        self.assertEqual(c.compare(old, self.observe())['installation-id'], 'verified')
        alias.unlink()
        with self.assertRaises(c.ContinuityError):
            c.compare(old, self.observe())

    def test_unaccounted_links_and_unsafe_metadata(self):
        path = self.create('control-token')
        alias = self.root / 'alias'
        os.link(path, alias)
        with self.assertRaises(c.ContinuityError):
            self.observe()
        alias.unlink()
        path.chmod(0o644)
        with self.assertRaises(c.ContinuityError):
            self.observe()
        path.unlink()
        path.symlink_to('/dev/null')
        with self.assertRaises(c.ContinuityError):
            self.observe()

    def test_unsafe_parent_not_absence(self):
        (self.root / 'var').symlink_to(self.root / 'missing')
        with self.assertRaises(c.ContinuityError):
            self.observe()

    def test_directory_or_account_change_refused(self):
        self.create('control-token')
        old = self.observe()
        with self.assertRaises(c.ContinuityError):
            self.observe(account=False)
        self.state.rename(self.state.with_name('old-state'))
        self.create('control-token')
        with self.assertRaises(c.ContinuityError):
            c.compare(old, self.observe(), allow_new=True)

    def test_between_walk_change_and_live_root_refused(self):
        path = self.create('control-token')
        walk = c._walk
        def mutate(*args):
            result = walk(*args)
            path.write_bytes(b'z'*64)
            return result
        with mock.patch.object(c, '_walk', side_effect=mutate):
            with self.assertRaises(c.ContinuityError):
                self.observe()
        with self.assertRaises(c.ContinuityError):
            c.observe('/', owner_uid=0, account=None)

    def test_new_process_cannot_compare_original_baseline(self):
        old = self.observe()
        with mock.patch.object(os, 'getpid', return_value=old.pid + 1):
            with self.assertRaises(c.ContinuityError):
                c.compare(old, self.observe())

    def test_absent_state_does_not_hide_replaced_ancestor(self):
        parent = self.state.parent
        parent.mkdir(parents=True)
        old = self.observe()
        parent.rename(parent.with_name('old-lib'))
        parent.mkdir()
        with self.assertRaises(c.ContinuityError):
            c.compare(old, self.observe(), allow_new=True)
