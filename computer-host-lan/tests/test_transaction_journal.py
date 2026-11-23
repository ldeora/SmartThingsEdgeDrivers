"""Rootless fixture tests for the isolated protected wizard journal.

No sudo, no real backups, no systemctl, no installed Linux agent changes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import transaction_journal as journal


class ProtectedJournalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = journal.ProtectedJournal(root=self.root, owner_uid=os.geteuid())
        self.directory = self.root / 'var/backups/linux-host-agent/wizard-transactions'

    def private_directory(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.root / 'var/backups/linux-host-agent').chmod(0o700)
        self.directory.chmod(0o700)

    def private_record(self, data: dict | str, *, mode: int = 0o600):
        self.private_directory()
        target = self.directory / 'journal.json'
        target.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
        target.chmod(mode)
        return target

    def test_missing_status_does_not_create_any_directories(self):
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertFalse((self.root / 'var').exists())

    def test_complete_sequence_and_atomic_private_files(self):
        self.store.begin('install')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'incomplete')
        self.store.advance('INSPECTED', 'STAGED')
        self.store.advance('STAGED', 'SNAPSHOTTED', snapshot_name='snapshot-abcdefgh')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'incomplete')
        for first, second in (
            ('SNAPSHOTTED', 'APPLYING'), ('APPLYING', 'ACTIVATING'),
            ('ACTIVATING', 'VERIFYING'), ('VERIFYING', 'COMMITTED'),
        ):
            self.store.advance(first, second)
            if second != 'COMMITTED':
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'recovery_required')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'incomplete')
        raw = self.directory / 'journal.json'
        self.assertEqual(stat.S_IMODE(raw.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.directory / 'lock').stat().st_mode), 0o600)
        self.assertEqual(json.loads(raw.read_text())['snapshot_name'], 'snapshot-abcdefgh')
        self.store.clear_committed()
        self.assertFalse(raw.exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_refuse_second_install_and_stale_transition(self):
        self.store.begin('upgrade')
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('repair')
        with self.assertRaises(journal.JournalConflict):
            self.store.advance('STAGED', 'SNAPSHOTTED', snapshot_name='snapshot-abcdefgh')
        with self.assertRaises(journal.JournalError):
            self.store.advance('INSPECTED', 'APPLYING')
        with self.assertRaises(journal.JournalConflict):
            self.store.clear_committed()
        self.assertEqual(json.loads((self.directory / 'journal.json').read_text())['phase'],
                         'INSPECTED')

    def test_reject_missing_and_malicious_snapshot_references(self):
        self.store.begin('install')
        self.store.advance('INSPECTED', 'STAGED')
        for bad in (None, '../snapshot-abcdefgh', '/var/backups/snapshot-abcdefgh',
                    'snapshot-a', 'snapshot-valid/../../escape', 'snapshot-invalid~'):
            with self.subTest(bad=bad):
                with self.assertRaises(journal.UnsafeJournal):
                    self.store.advance('STAGED', 'SNAPSHOTTED', snapshot_name=bad)
        self.store.advance('STAGED', 'SNAPSHOTTED', snapshot_name='snapshot-valid_123')

    def test_reject_symlinked_parent_directory(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'var').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        with self.assertRaises(journal.UnsafeJournal):
            self.store.begin('install')
        self.assertEqual(list(outside.iterdir()), [])

    def test_reject_symlinked_journal_without_reading_target(self):
        outside = self.root / 'secret'
        outside.write_text('PRIVATE-TOKEN')
        self.private_directory()
        (self.directory / 'journal.json').symlink_to(outside)
        with self.assertRaises(journal.UnsafeJournal) as raised:
            self.store.public_status()
        self.assertNotIn('PRIVATE-TOKEN', str(raised.exception))
        self.assertEqual(outside.read_text(), 'PRIVATE-TOKEN')

    def test_reject_hardlink_and_world_readable_file(self):
        doc = self.private_record({
            'schema': 1, 'operation': 'install', 'phase': 'INSPECTED',
            'snapshot_name': None,
        })
        outside = self.root / 'second-link'
        os.link(doc, outside)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        outside.unlink()
        doc.chmod(0o644)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()

    def test_reject_world_writable_parents_and_private_directory(self):
        self.private_directory()
        (self.root / 'var').chmod(0o777)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        (self.root / 'var').chmod(0o755)
        self.directory.chmod(0o750)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()

    def test_untrusted_fields_and_invalid_json_fail_closed(self):
        data = {'schema': 1, 'operation': 'upgrade', 'phase': 'STAGED',
                'snapshot_name': None}
        for payload in (
            dict(data, uuid='12345678-1234-1234-1234-123456789abc'),
            dict(data, operation='bogus'),
            dict(data, schema=True),
            dict(data, phase='../../etc/passwd'),
            dict(data, snapshot_name='snapshot-abcdefghi'),
        ):
            with self.subTest(payload=payload):
                self.private_record(payload)
                with self.assertRaises(journal.UnsafeJournal):
                    self.store.public_status()
        for payload in ('{"schema":1,"schema":1}', '[]', '{malformed',
                        ' ' * 2049, '{"schema":1}'):
            with self.subTest(payload=payload[:30]):
                self.private_record(payload)
                with self.assertRaises(journal.UnsafeJournal):
                    self.store.public_status()

    def test_incomplete_temp_markers_block_new_transaction(self):
        self.private_directory()
        marker = self.directory / '.wizard-journal-uncertain'
        marker.write_text('possibly interrupted')
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('install')
        self.assertTrue(marker.exists())

    def test_recovery_status_is_allowlisted_and_never_exposes_snapshot_or_key(self):
        self.store.begin('repair')
        self.store.advance('INSPECTED', 'STAGED')
        self.store.advance('STAGED', 'SNAPSHOTTED', snapshot_name='snapshot-secret_sentinel')
        self.store.advance('SNAPSHOTTED', 'APPLYING')
        status = self.store.public_status()
        self.assertEqual(status, {
            'schema_version': 1, 'operation': 'protected_status',
            'mode': 'privileged_read_only',
            'privileged_transaction_state': 'recovery_required',
            'secrets_included': False,
        })
        self.assertNotIn('snapshot-secret_sentinel', json.dumps(status))
        self.assertNotIn('snapshot', json.dumps(status))

    def test_lock_symlink_rejected_without_touching_target(self):
        outside = self.root / 'outside'
        outside.write_text('keep')
        self.private_directory()
        (self.directory / 'lock').symlink_to(outside)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.begin('install')
        self.assertEqual(outside.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
