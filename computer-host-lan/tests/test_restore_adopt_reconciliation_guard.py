"""All schema-2 journal discard paths recheck after ancestry sync."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_restore_adopt_journal as fixtures
from test_restore_adopt_contract import ADOPT, ADOPT_EVIDENCE, initial

v2 = fixtures.v2
old = fixtures.old


class ReconciliationGuardTests(unittest.TestCase):
    def exercise(self, kind, fault):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'run/lock').mkdir(parents=True)
            store = v2.FixtureJournal(root)
            path = root / 'var/backups/linux-host-agent/wizard-transactions/journal.json'
            if kind == 'orphan':
                with mock.patch.object(v2.os, 'replace', side_effect=OSError('fixture')):
                    with self.assertRaises(old.UnsafeJournal):
                        with store.transaction(ADOPT):
                            self.fail('unexpected handle')
                temp, = path.parent.glob('.wizard-journal-*')
                temp.write_bytes(temp.read_bytes()[:-1])
                run = lambda verify: store.reconcile_partial_orphan_temp(
                    confirmation='RECONCILE_ORPHAN', verify=verify)
            else:
                with store.transaction(ADOPT) as handle:
                    current = handle.record()
                candidate = dict(current, phase='STAGED', evidence=ADOPT_EVIDENCE)
                temp = path.parent / ('.wizard-journal-' + 'a' * 32)
                raw = v2.canonical(candidate)
                temp.write_bytes(raw if kind == 'complete' else raw[:20])
                temp.chmod(0o600)
                if kind == 'complete':
                    run = store.reconcile_complete_temp
                else:
                    run = lambda verify: store.reconcile_partial_temp(candidate, verify)
            initial_bytes = temp.read_bytes()
            sync = v2._sync_ancestors
            evidence = [temp]

            def mutate(root_arg, uid):
                sync(root_arg, uid)
                if fault == 'bytes':
                    temp.write_bytes(b'changed after sync')
                elif fault == 'inode':
                    moved = temp.with_name('retained-temp')
                    temp.rename(moved)
                    temp.write_bytes(initial_bytes)
                    temp.chmod(0o600)
                    evidence.append(moved)
                elif fault == 'namespace':
                    moved = path.parent.with_name('retained-journal')
                    path.parent.rename(moved)
                    path.parent.mkdir(mode=0o700)
                    evidence[:] = [moved / temp.name]
                elif fault == 'lock':
                    lock = path.parent / old._LOCK
                    lock.rename(lock.with_name('retained-lock'))
                    lock.touch(mode=0o600)
                elif fault == 'predecessor':
                    if path.exists():
                        original = path.read_bytes()
                        path.rename(path.with_name('retained-record'))
                        path.write_bytes(original)
                    else:
                        path.write_bytes(v2.canonical(initial(ADOPT)))
                    path.chmod(0o600)
                elif fault == 'extra':
                    (path.parent / 'foreign').touch(mode=0o600)
                elif fault == 'stage':
                    stage = root / 'var/lib/computer-host-installer/staging'
                    stage.mkdir(parents=True, mode=0o700)
                    stage.parent.chmod(0o700)
                    (stage / 'foreign').touch(mode=0o600)
                elif fault == 'sync_failure':
                    raise OSError('fixture sync failure')

            verify = mock.Mock(return_value=True)
            with mock.patch.object(v2, '_sync_ancestors', side_effect=mutate):
                if fault == 'none':
                    run(verify)
                    self.assertFalse(temp.exists())
                else:
                    with self.assertRaises(old.JournalError):
                        run(verify)
                    self.assertTrue(all(p.exists() for p in evidence))
                    if fault == 'bytes':
                        self.assertEqual(temp.read_bytes(), b'changed after sync')
                    else:
                        self.assertEqual(evidence[0].read_bytes(), initial_bytes)
            verify.assert_called_once()

    def test_all_paths_accept_unchanged_evidence(self):
        for kind in ('complete', 'partial', 'orphan'):
            with self.subTest(kind=kind):
                self.exercise(kind, 'none')

    def test_all_paths_preserve_changed_evidence(self):
        for kind in ('complete', 'partial', 'orphan'):
            for fault in ('bytes', 'inode', 'namespace', 'lock', 'predecessor',
                          'extra', 'sync_failure'):
                with self.subTest(kind=kind, fault=fault):
                    self.exercise(kind, fault)

    def test_orphan_stage_after_sync_blocks_discard(self):
        self.exercise('orphan', 'stage')
