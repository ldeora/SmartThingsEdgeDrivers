"""Non-root, no-systemd regressions for the isolated protected journal.

No sudo, no real backups, no systemd, no installed agent or service changes.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import transaction_journal as journal

PHASES = ('INSPECTED', 'STAGED', 'SNAPSHOTTED', 'APPLYING',
          'ACTIVATING', 'VERIFYING', 'COMMITTED')
SNAPSHOT = 'snapshot-abcdefgh'


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

    @staticmethod
    def record(*, phase='INSPECTED', snapshot=None):
        return {'schema': 1, 'transaction_id': 'a' * 32,
                'operation': 'install', 'phase': phase, 'snapshot_name': snapshot}

    @staticmethod
    def advance_to(handle, phase):
        for i in range(1, PHASES.index(phase) + 1):
            handle.advance(PHASES[i - 1], PHASES[i],
                           snapshot_name=SNAPSHOT if PHASES[i] == 'SNAPSHOTTED' else None)

    def test_unknown_wol_operation_is_never_recovered_as_agent_transaction(self):
        record = dict(self.record(phase='APPLYING', snapshot=SNAPSHOT),
                      operation='configure_wol')
        target = self.private_record(record)
        before = target.read_bytes()
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        with self.assertRaises(journal.UnsafeJournal):
            self.store.resume_recovery()
        self.assertEqual(target.read_bytes(), before)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.begin('install')
        self.assertEqual(target.read_bytes(), before)

    def test_status_does_not_create_directories_or_lock(self):
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        self.assertFalse((self.root / 'var').exists())
        with self.store.begin('install'):
            pass
        lock = self.directory / 'lock'
        before = lock.stat().st_mtime_ns
        with mock.patch.object(journal.os, 'open', wraps=os.open) as opened:
            self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                             'incomplete')
        calls = [c for c in opened.call_args_list if c.args and c.args[0] == 'lock']
        self.assertTrue(calls)
        self.assertTrue(all(not c.args[1] & os.O_CREAT for c in calls))
        self.assertTrue(all(c.args[1] & os.O_ACCMODE == os.O_RDONLY for c in calls))
        self.assertEqual(before, lock.stat().st_mtime_ns)

    def test_status_readers_share_locks_without_false_in_progress(self):
        # A status call owns SH, not EX: another concurrent SH-status must
        # report the journal state rather than misclassifying a live writer.
        with self.store.begin('install'):
            pass  # An incomplete journal with no active transaction owner.
        lock = self.directory / 'lock'
        fd1 = os.open(lock, os.O_RDONLY | os.O_CLOEXEC)
        fd2 = os.open(lock, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.flock(fd1, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fd2, fcntl.LOCK_SH | fcntl.LOCK_NB)
            statuses = []
            barrier = threading.Barrier(3)

            def query():
                barrier.wait(timeout=3)
                statuses.append(self.store.public_status()['privileged_transaction_state'])

            readers = [threading.Thread(target=query) for _ in range(2)]
            for reader in readers:
                reader.start()
            barrier.wait(timeout=3)
            for reader in readers:
                reader.join(timeout=5)
                self.assertFalse(reader.is_alive())
            self.assertEqual(statuses, ['incomplete', 'incomplete'])
        finally:
            os.close(fd1)
            os.close(fd2)

    def test_begin_retries_boundedly_behind_status_reader(self):
        # Set up a harmless status-side SH lock with no journal. begin()
        # must wait for this reader rather than report a running install.
        with self.store.begin('install') as tx:
            tx.abort()
            tx.clear_finished()
        lock = self.directory / 'lock'
        reader_fd = os.open(lock, os.O_RDONLY | os.O_CLOEXEC)
        fcntl.flock(reader_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        reader_closed = threading.Event()

        def release_reader():
            try:
                time.sleep(0.15)
            finally:
                os.close(reader_fd)
                reader_closed.set()

        release = threading.Thread(target=release_reader)
        release.start()
        try:
            self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                             'none')
            started = time.monotonic()
            with self.store.begin('upgrade') as tx:
                elapsed = time.monotonic() - started
                self.assertGreaterEqual(elapsed, 0.09)
                self.assertLess(elapsed, journal._LOCK_WAIT_SECONDS + 1.0)
                tx.abort()
                tx.clear_finished()
        finally:
            release.join(timeout=3)
        self.assertTrue(reader_closed.is_set())

    def test_existing_exclusive_transaction_still_fails_in_bounded_time(self):
        with self.store.begin('install'):
            started = time.monotonic()
            with self.assertRaises(journal.JournalConflict):
                self.store.begin('upgrade')
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, journal._LOCK_WAIT_SECONDS - 0.05)
            self.assertLess(elapsed, journal._LOCK_WAIT_SECONDS + 1.0)

    def test_new_directory_modes_are_independent_of_umask(self):
        previous = os.umask(0o077)
        try:
            with self.store.begin('install') as tx:
                tx.abort()
                tx.clear_finished()
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE((self.root / 'var').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.root / 'var/backups').stat().st_mode),
                         0o755)
        self.assertEqual(stat.S_IMODE((self.root / 'var/backups/linux-host-agent').stat().st_mode),
                         0o700)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)

    def test_existing_backup_parent_permissions_are_never_normalized(self):
        parent = self.root / 'var/backups'
        parent.mkdir(parents=True)
        parent.chmod(0o700)
        with self.store.begin('install') as tx:
            tx.abort()
            tx.clear_finished()
        self.assertEqual(stat.S_IMODE(parent.stat().st_mode), 0o700)

    def test_lifetime_handle_and_complete_sequence(self):
        with self.store.begin('install') as tx:
            self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                             'in_progress')
            for i in range(1, len(PHASES)):
                tx.advance(PHASES[i - 1], PHASES[i],
                           snapshot_name=SNAPSHOT if PHASES[i] == 'SNAPSHOTTED' else None)
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'in_progress')
            self.assertEqual(stat.S_IMODE((self.directory / 'journal.json').stat().st_mode),
                             0o600)
            self.assertEqual(stat.S_IMODE((self.directory / 'lock').stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
            tx.clear_finished()
            self.assertFalse((self.directory / 'journal.json').exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_abort_before_apply_even_after_snapshot(self):
        for phase in ('INSPECTED', 'STAGED', 'SNAPSHOTTED'):
            with self.subTest(phase=phase):
                with self.store.begin('upgrade') as tx:
                    self.advance_to(tx, phase)
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'incomplete')
                with self.store.resume_recovery() as recovery:
                    recovery.abort()
                    self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                     'in_progress')
                    record = json.loads((self.directory / 'journal.json').read_text())
                    self.assertEqual(record['phase'], 'ABORTED')
                    recovery.clear_finished()
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'none')

    def test_rollback_completion_requires_verified_snapshot_restore(self):
        with self.store.begin('repair') as tx:
            self.advance_to(tx, 'ACTIVATING')
            with self.assertRaises(journal.JournalConflict):
                tx.abort()
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        with self.store.resume_recovery() as recovered:
            with self.assertRaises(journal.JournalConflict):
                recovered.mark_rolled_back(lambda _: False)
            with self.assertRaises(journal.JournalConflict):
                recovered.mark_rolled_back(None)
            observed = []
            recovered.mark_rolled_back(lambda name: observed.append(name) or name == SNAPSHOT)
            self.assertEqual(observed, [SNAPSHOT])
            self.assertEqual(json.loads((self.directory / 'journal.json').read_text())['phase'],
                             'ROLLED_BACK')
            recovered.clear_finished()
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_committed_journal_is_complete_and_reaped_at_next_begin(self):
        with self.store.begin('install') as tx:
            self.advance_to(tx, 'COMMITTED')
            committed_id = json.loads((self.directory / 'journal.json').read_text())['transaction_id']
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        with self.store.begin('upgrade') as tx:
            fresh = json.loads((self.directory / 'journal.json').read_text())
            self.assertNotEqual(fresh['transaction_id'], committed_id)
            tx.abort()
            tx.clear_finished()
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_interrupted_terminal_cleanup_can_finish_without_manual_deletion(self):
        with self.store.begin('install') as tx:
            self.advance_to(tx, 'COMMITTED')
        marker = self.directory / ('.wizard-journal-' + 'b' * 32)
        marker.write_bytes(b'abandoned write')
        marker.chmod(0o600)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('upgrade')
        self.store.finish_terminal()
        self.assertFalse(marker.exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_finished_cleanup_cannot_discard_unfinished_record(self):
        with self.store.begin('install'):
            pass
        with self.assertRaises(journal.JournalConflict):
            self.store.finish_terminal()
        self.assertTrue((self.directory / 'journal.json').exists())

    def test_second_caller_cannot_begin_resume_or_advance(self):
        with self.store.begin('install') as tx:
            with self.assertRaises(journal.JournalConflict):
                self.store.begin('upgrade')
            with self.assertRaises(journal.JournalConflict):
                self.store.resume_recovery()
            self.advance_to(tx, 'STAGED')
        with self.assertRaises(journal.JournalConflict):
            tx.advance('STAGED', 'SNAPSHOTTED', snapshot_name=SNAPSHOT)
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('upgrade')

    def test_invalid_snapshot_and_phase_fail_without_mutating(self):
        with self.store.begin('install') as tx:
            tx.advance('INSPECTED', 'STAGED')
            for bad in (None, '../snapshot-abcdefgh', '/tmp/snapshot-abcdefgh',
                        'snapshot-a', 'snapshot-valid/../../escape', 'snapshot-invalid~'):
                with self.subTest(bad=bad):
                    with self.assertRaises(journal.UnsafeJournal):
                        tx.advance('STAGED', 'SNAPSHOTTED', snapshot_name=bad)
            with self.assertRaises(journal.JournalError):
                tx.advance('STAGED', 'ACTIVATING')
            with self.assertRaises(journal.JournalConflict):
                tx.advance('INSPECTED', 'STAGED')
            self.assertEqual(json.loads((self.directory / 'journal.json').read_text())['phase'],
                             'STAGED')

    def test_failed_phase_write_keeps_temp_and_requires_verified_abort(self):
        with self.store.begin('install') as tx:
            with mock.patch.object(journal.os, 'replace', side_effect=OSError('simulated')):
                with self.assertRaises(journal.UnsafeJournal):
                    tx.advance('INSPECTED', 'STAGED')
        self.assertTrue(any(n.startswith('.wizard-journal-')
                            for n in os.listdir(self.directory)))
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('install')
        with self.store.resume_recovery() as tx:
            with self.assertRaises(journal.JournalConflict):
                tx.abort()
            with self.assertRaises(journal.JournalConflict):
                tx.abort(lambda _: False)
            tx.abort(lambda _: True)  # Fixture's trusted unchanged-state check.
            tx.clear_finished()
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_stale_journal_handle_cannot_hide_failed_update_or_cleanup(self):
        # Reproduce the Gentoo/Btrfs pre-population directory stream:
        # a descriptor opened before .wizard-journal-* was written still
        # sees the old entries, while a freshly opened stream sees it.
        original_listdir = os.listdir

        with self.store.begin('install') as tx:
            original_directory = tx._directory

            def stale_listdir(fd):
                names = original_listdir(fd)
                if fd == original_directory:
                    return [name for name in names
                            if not name.startswith('.wizard-journal-')]
                return names

            with mock.patch.object(journal.os, 'listdir', side_effect=stale_listdir):
                with mock.patch.object(journal.os, 'replace',
                                       side_effect=OSError('simulated EIO')):
                    with self.assertRaises(journal.UnsafeJournal):
                        tx.advance('INSPECTED', 'STAGED')
                self.assertTrue(any(n.startswith('.wizard-journal-')
                                    for n in original_listdir(self.directory)))
                # A failed journal write must NEVER look clean even when
                # the lifetime-held descriptor returns a stale listing.
                with self.assertRaises(journal.JournalConflict):
                    tx.advance('INSPECTED', 'STAGED')
                with self.assertRaises(journal.JournalConflict):
                    tx.abort(lambda _: False)
                tx.abort(lambda _: True)
                tx.clear_finished()

        self.assertFalse(any(n.startswith('.wizard-journal-')
                             for n in os.listdir(self.directory)))
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_stale_journal_handle_clear_finished_reaps_new_temp_marker(self):
        original_listdir = os.listdir
        with self.store.begin('install') as tx:
            original_directory = tx._directory
            tx.abort()
            marker = self.directory / ('.wizard-journal-' + 'c' * 32)
            marker.write_bytes(b'simulated leftover')
            marker.chmod(0o600)

            def stale_listdir(fd):
                names = original_listdir(fd)
                if fd == original_directory:
                    return [name for name in names
                            if not name.startswith('.wizard-journal-')]
                return names

            with mock.patch.object(journal.os, 'listdir', side_effect=stale_listdir):
                tx.clear_finished()

        self.assertFalse(marker.exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')

    def test_failed_initial_write_requires_verified_orphan_reconciliation(self):
        with mock.patch.object(journal.os, 'replace', side_effect=OSError('simulated')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('install')
        self.assertFalse((self.directory / 'journal.json').exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')
        with self.assertRaises(journal.JournalConflict):
            self.store.begin('install')
        with self.assertRaises(journal.JournalConflict):
            self.store.reconcile_orphaned_staging(lambda: False)
        self.store.reconcile_orphaned_staging(lambda: True)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'], 'none')
        with self.store.begin('install') as tx:
            tx.abort()
            tx.clear_finished()

    def test_orphaned_valid_applying_record_without_journal_is_not_deleted(self):
        # An unexpected lost journal.json must NOT make an APPLYING temp
        # record look like a harmless interrupted first INSPECTED write.
        with mock.patch.object(journal.os, 'replace',
                               side_effect=OSError('simulated initial EIO')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('install')
        marker, = self.directory.glob('.wizard-journal-*')
        record = self.record(phase='APPLYING', snapshot=SNAPSHOT)
        raw = (json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode()
        for payload in (raw, raw[:65]):
            with self.subTest(bytes=len(payload)):
                marker.write_bytes(payload)
                with self.assertRaises(journal.JournalConflict):
                    self.store.reconcile_orphaned_staging(lambda: True)
                self.assertEqual(marker.read_bytes(), payload)
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'recovery_required')

    def test_orphaned_empty_or_partial_initial_write_can_be_reconciled(self):
        # A failed write can leave any prefix of the canonical INSPECTED
        # record. A fully verified first-record prefix is safe to remove.
        for remaining in (0, 17, 57, 97, -1):
            with self.subTest(remaining=remaining):
                with mock.patch.object(journal.os, 'replace',
                                       side_effect=OSError('simulated initial EIO')):
                    with self.assertRaises(journal.UnsafeJournal):
                        self.store.begin('install')
                marker, = self.directory.glob('.wizard-journal-*')
                original = marker.read_bytes()
                marker.write_bytes(original[:remaining])
                self.store.reconcile_orphaned_staging(lambda: True)
                self.assertFalse(marker.exists())
                self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                                 'none')

    def test_orphaned_malformed_complete_record_is_not_deleted(self):
        with mock.patch.object(journal.os, 'replace',
                               side_effect=OSError('simulated initial EIO')):
            with self.assertRaises(journal.UnsafeJournal):
                self.store.begin('install')
        marker, = self.directory.glob('.wizard-journal-*')
        marker.write_bytes(b'{"phase":"INSPECTED","unknown":true}\n')
        with self.assertRaises(journal.JournalConflict):
            self.store.reconcile_orphaned_staging(lambda: True)
        self.assertTrue(marker.exists())
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'recovery_required')

    def test_symlinks_hardlinks_and_unsafe_permissions_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'var').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.begin('install')
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        (self.root / 'var').unlink()

        doc = self.private_record(self.record())
        outside_link = self.root / 'second-link'
        os.link(doc, outside_link)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        outside_link.unlink()
        doc.chmod(0o644)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        doc.chmod(0o600)
        self.directory.chmod(0o750)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        self.directory.chmod(0o700)
        (self.root / 'var').chmod(0o777)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()

    def test_journal_and_lock_symlink_refuse_to_read_or_touch_target(self):
        outside = self.root / 'secret'
        outside.write_text('PRIVATE-TOKEN')
        self.private_directory()
        (self.directory / 'journal.json').symlink_to(outside)
        with self.assertRaises(journal.UnsafeJournal) as raised:
            self.store.public_status()
        self.assertNotIn('PRIVATE-TOKEN', str(raised.exception))
        (self.directory / 'journal.json').unlink()
        (self.directory / 'lock').symlink_to(outside)
        with self.assertRaises(journal.UnsafeJournal):
            self.store.begin('install')
        with self.assertRaises(journal.UnsafeJournal):
            self.store.public_status()
        self.assertEqual(outside.read_text(), 'PRIVATE-TOKEN')

    def test_duplicate_invalid_fields_and_overlarge_json_fail_closed(self):
        variants = (
            dict(self.record(), uuid='12345678-1234-1234-1234-123456789abc'),
            dict(self.record(), operation='bogus'),
            dict(self.record(), schema=True),
            dict(self.record(), transaction_id='\u0000'),
            dict(self.record(), phase='../../etc/passwd'),
            self.record(phase='ROLLED_BACK', snapshot=None),
            self.record(phase='STAGED', snapshot=SNAPSHOT),
        )
        for payload in variants:
            with self.subTest(payload=repr(payload)[:60]):
                self.private_record(payload)
                with self.assertRaises(journal.UnsafeJournal):
                    self.store.public_status()
        for payload in ('{"schema":1,"schema":1}', '[]', '{broken',
                        ' ' * 2049, '{"schema":1}'):
            self.private_record(payload)
            with self.assertRaises(journal.UnsafeJournal):
                self.store.public_status()

    def test_redacted_public_status_and_normal_parent_modes(self):
        with self.store.begin('install') as tx:
            self.advance_to(tx, 'APPLYING')
        data = self.store.public_status()
        self.assertEqual(data, {
            'schema_version': 1, 'operation': 'protected_status',
            'mode': 'privileged_read_only',
            'privileged_transaction_state': 'recovery_required',
            'secrets_included': False,
        })
        self.assertNotIn(SNAPSHOT, json.dumps(data))
        self.assertEqual(stat.S_IMODE((self.root / 'var').stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.root / 'var/backups').stat().st_mode), 0o755)

    def test_status_active_other_process_then_crash(self):
        script = """
import os, pathlib, sys, time
sys.path.insert(0, sys.argv[2])
from transaction_journal import ProtectedJournal
store = ProtectedJournal(root=pathlib.Path(sys.argv[1]), owner_uid=os.geteuid())
with store.begin('install'):
    print('READY', flush=True)
    time.sleep(30)
"""
        proc = subprocess.Popen([sys.executable, '-c', script, str(self.root),
                                 str(ROOT / 'scripts')],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), 'READY')
            self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                             'in_progress')
            with self.assertRaises(journal.JournalConflict):
                self.store.begin('repair')
            with self.assertRaises(journal.JournalConflict):
                self.store.resume_recovery()
        finally:
            proc.kill()
            proc.communicate(timeout=5)
        self.assertEqual(self.store.public_status()['privileged_transaction_state'],
                         'incomplete')
        with self.store.resume_recovery() as tx:
            tx.abort()
            tx.clear_finished()

    def test_crash_at_each_phase_can_be_resolved_without_root_file_deletion(self):
        script = """
import os, pathlib, sys
sys.path.insert(0, sys.argv[2])
from transaction_journal import ProtectedJournal
phases = ('INSPECTED', 'STAGED', 'SNAPSHOTTED', 'APPLYING',
          'ACTIVATING', 'VERIFYING', 'COMMITTED')
with ProtectedJournal(root=pathlib.Path(sys.argv[1]), owner_uid=os.geteuid()).begin('install') as tx:
    for i in range(1, phases.index(sys.argv[3]) + 1):
        tx.advance(phases[i-1], phases[i],
                   snapshot_name='snapshot-abcdefgh' if phases[i]=='SNAPSHOTTED' else None)
    os._exit(17)
"""
        for phase in PHASES:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                child = subprocess.run([sys.executable, '-c', script, tmp,
                                        str(ROOT / 'scripts'), phase],
                                       capture_output=True, text=True, timeout=10)
                self.assertEqual(child.returncode, 17, child.stderr)
                store = journal.ProtectedJournal(root=Path(tmp), owner_uid=os.geteuid())
                expected = ('none' if phase == 'COMMITTED' else
                            'incomplete' if phase in PHASES[:3] else 'recovery_required')
                self.assertEqual(store.public_status()['privileged_transaction_state'],
                                 expected)
                if phase == 'COMMITTED':
                    with store.begin('repair') as tx:
                        tx.abort()
                        tx.clear_finished()
                else:
                    with store.resume_recovery() as tx:
                        if phase in PHASES[:3]:
                            tx.abort()
                        else:
                            tx.mark_rolled_back(lambda snap: snap == SNAPSHOT)
                        tx.clear_finished()
                self.assertEqual(store.public_status()['privileged_transaction_state'],
                                 'none')


if __name__ == '__main__':
    unittest.main()
