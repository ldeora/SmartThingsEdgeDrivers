"""Protected staged plan data fixtures."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_core as core
import restore_adopt_journal as journal
import restore_adopt_stage as stage
import transaction_journal as old
from test_restore_adopt_contract import ADOPT, ADOPT_EVIDENCE, RESTORE

SERVICES = dict(agent_active=True, agent_enabled=True, socket_active=False, socket_enabled=False)

def files():
    optional = {core.POWER_DROPIN, core.WOL_DROPIN, core.AVAHI_PATH}
    return tuple(core.Change(path, None if path in optional else b'fixture data\n',
                             0o755 if path in core.APP_FILES else 0o644)
                 for path in sorted(core.MANAGED_PATHS))

class StageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'run/lock').mkdir(parents=True)
        self.store = journal.FixtureJournal(self.root)
        self.base = self.root / 'var/lib/computer-host-installer/staging'

    def test_publish_verify_and_pin_bytes(self):
        with self.store.transaction(ADOPT) as handle:
            digest = stage.stage_plan(handle, files(), SERVICES)
            ready, = self.base.glob('ready-plan-*')
            self.assertEqual(hashlib.sha256((ready / 'manifest.json').read_bytes()).hexdigest(), digest)
            plan = stage.read_plan(handle, initial_digest=digest)
            self.assertEqual(plan.digest, digest)
            self.assertEqual({f.path: f.content for f in plan.files},
                             {f.path: f.content for f in files()})
            self.assertEqual(dict(plan.services), SERVICES)
            with self.assertRaises(stage.PlanError):
                stage.stage_plan(handle, files(), SERVICES)
            handle.advance('STAGED', evidence=dict(ADOPT_EVIDENCE, staged_plan_sha256=digest),
                           verify=lambda _: stage.read_plan(handle, initial_digest=digest).digest == digest)
            self.assertEqual(stage.read_plan(handle), plan)
            with self.assertRaises(stage.PlanError):
                stage.read_plan(handle, initial_digest=digest)
            first = next(ready.glob('*.data'))
            first.write_bytes(b'changed')
            with self.assertRaises(stage.PlanError):
                stage.read_plan(handle)
            self.assertIn(b'fixture data\n', [f.content for f in plan.files])
        self.assertTrue(old._staged_payload_remains(self.root, os.geteuid()))

    def test_reject_partial_duplicate_unsafe_mode_and_wrong_power(self):
        with self.store.transaction(ADOPT) as handle:
            plan = files()
            first = next(f for f in plan if f.content is not None)
            for invalid in (plan[:-1], plan + (plan[0],),
                            tuple(core.Change(f.path, f.content, 0o777)
                                  if f == first else f for f in plan),
                            tuple(core.Change(f.path, b'power')
                                  if f.path == core.POWER_DROPIN else f for f in plan)):
                with self.assertRaises(stage.PlanError):
                    stage.stage_plan(handle, invalid, SERVICES)
            self.assertFalse(self.base.exists())

    def test_tampering_extra_link_and_mode_refused(self):
        with self.store.transaction(RESTORE) as handle:
            digest = stage.stage_plan(handle, files(), SERVICES)
            ready, = self.base.glob('ready-plan-*')
            extra = ready / 'extra'
            extra.write_bytes(b'extra')
            with self.assertRaises(stage.PlanError):
                stage.read_plan(handle, initial_digest=digest)
            extra.unlink()
            original = next(ready.glob('*.data'))
            link = self.root / 'linked'
            os.link(original, link)
            with self.assertRaises(stage.legacy_stage.StagingError):
                stage.read_plan(handle, initial_digest=digest)
            link.unlink()
            original.chmod(0o644)
            with self.assertRaises(stage.legacy_stage.StagingError):
                stage.read_plan(handle, initial_digest=digest)

    def test_post_rename_sync_failure_prevents_forward_use(self):
        with self.store.transaction(ADOPT) as handle:
            with mock.patch.object(stage, '_sync_stage_ancestors',
                                   side_effect=OSError('fixture sync')):
                with self.assertRaises(stage.PlanError):
                    stage.stage_plan(handle, files(), SERVICES)
            ready, = self.base.glob('ready-plan-*')
            self.assertTrue(ready.is_dir())
            with self.assertRaises(old.JournalConflict):
                handle.advance('STAGED', evidence=ADOPT_EVIDENCE, verify=lambda _: True)
        with self.store.transaction() as recovery:
            self.assertEqual(recovery.record()['phase'], 'INSPECTED')
            with self.assertRaises(stage.PlanError):
                stage.stage_plan(recovery, files(), SERVICES)

    def test_interrupted_publication_remains_visible_to_legacy(self):
        with self.store.transaction(ADOPT) as handle:
            with mock.patch.object(stage.os, 'rename', side_effect=OSError('fixture')):
                with self.assertRaises(stage.PlanError):
                    stage.stage_plan(handle, files(), SERVICES)
            pending, = self.base.glob('pending-plan-*')
            self.assertTrue(pending.is_dir())
            self.assertFalse(list(self.base.glob('ready-plan-*')))
            with self.assertRaises(old.JournalConflict):
                stage.stage_plan(handle, files(), SERVICES)
        with self.store.transaction() as recovery:
            with self.assertRaises(stage.PlanError):
                stage.stage_plan(recovery, files(), SERVICES)
            recovery.advance('ABORTED', verify=lambda _: True)
            with self.assertRaises(old.JournalConflict):
                recovery.clear_finished(lambda _: True)
        self.assertTrue(pending.is_dir())

    def test_terminal_retirement_allows_clean_finish(self):
        for intent in (ADOPT, RESTORE):
            with self.subTest(action=intent['action']):
                with self.store.transaction(intent) as handle:
                    digest = stage.stage_plan(handle, files(), SERVICES)
                    evidence = (ADOPT_EVIDENCE if intent == ADOPT else
                                __import__('test_restore_adopt_contract').RESTORE_EVIDENCE)
                    handle.advance('STAGED', evidence=dict(evidence, staged_plan_sha256=digest),
                                   verify=lambda _: True)
                    with self.assertRaises(stage.PlanError):
                        stage.retire_terminal_plan(handle)
                    handle.advance('ABORTED', verify=lambda _: True)
                    with self.assertRaises(old.JournalConflict):
                        handle.clear_finished(lambda _: True)
                    stage.retire_terminal_plan(handle)
                    stage.retire_terminal_plan(handle)
                    handle.clear_finished(lambda _: True)
                self.assertFalse(old._staged_payload_remains(self.root, os.geteuid()))

    def test_pending_retirement_and_retry_after_partial_delete(self):
        with self.store.transaction(ADOPT) as handle:
            with mock.patch.object(stage.os, 'rename', side_effect=OSError('fixture')):
                with self.assertRaises(stage.PlanError):
                    stage.stage_plan(handle, files(), SERVICES)
        with self.store.transaction() as recovery:
            recovery.advance('ABORTED', verify=lambda _: True)
            real_unlink = os.unlink
            calls = []

            def unlink(name, *args, **kwargs):
                calls.append(name)
                if len(calls) == 2:
                    raise OSError('fixture interrupted deletion')
                return real_unlink(name, *args, **kwargs)

            with mock.patch.object(stage.os, 'unlink', side_effect=unlink):
                with self.assertRaises(stage.PlanError):
                    stage.retire_terminal_plan(recovery)
            retiring, = self.base.glob('retiring-plan-*')
            self.assertTrue(retiring.is_dir())
            with self.assertRaises(old.JournalConflict):
                recovery.clear_finished(lambda _: True)
        with self.store.transaction() as recovery:
            stage.retire_terminal_plan(recovery)
            recovery.clear_finished(lambda _: True)
        self.assertFalse(old._staged_payload_remains(self.root, os.geteuid()))

    def test_retirement_refuses_foreign_entries_before_removing_anything(self):
        with self.store.transaction(ADOPT) as handle:
            stage.stage_plan(handle, files(), SERVICES)
            handle.advance('ABORTED', verify=lambda _: True)
            ready, = self.base.glob('ready-plan-*')
            extra = ready / 'unknown'
            extra.write_bytes(b'do not remove')
            before = {p.name: p.read_bytes() for p in ready.iterdir()}
            with self.assertRaises(stage.PlanError):
                stage.retire_terminal_plan(handle)
            self.assertEqual({p.name: p.read_bytes() for p in ready.iterdir()}, before)
            extra.unlink()
            foreign = self.base / 'pending-plan-foreign'
            foreign.mkdir()
            with self.assertRaises(stage.PlanError):
                stage.retire_terminal_plan(handle)
            self.assertTrue(foreign.is_dir())
            foreign.rmdir()
            stage.retire_terminal_plan(handle)
            handle.clear_finished(lambda _: True)

    def test_ready_digest_mismatch_refuses_retirement(self):
        with self.store.transaction(ADOPT) as handle:
            digest = stage.stage_plan(handle, files(), SERVICES)
            handle.advance('STAGED', evidence=dict(ADOPT_EVIDENCE, staged_plan_sha256=digest),
                           verify=lambda _: True)
            handle.advance('ABORTED', verify=lambda _: True)
            ready, = self.base.glob('ready-plan-*')
            first = next(ready.glob('*.data'))
            first.write_bytes(b'changed')
            before = {p.name: p.read_bytes() for p in ready.iterdir()}
            with self.assertRaises(stage.PlanError):
                stage.retire_terminal_plan(handle)
            self.assertEqual({p.name: p.read_bytes() for p in ready.iterdir()}, before)

    def test_retirement_rename_sync_failure_removes_no_data(self):
        with self.store.transaction(ADOPT) as handle:
            stage.stage_plan(handle, files(), SERVICES)
            handle.advance('ABORTED', verify=lambda _: True)
            ready, = self.base.glob('ready-plan-*')
            before = {p.name: p.read_bytes() for p in ready.iterdir()}
            with mock.patch.object(stage, '_sync_stage_ancestors',
                                   side_effect=OSError('fixture sync')):
                with self.assertRaises(stage.PlanError):
                    stage.retire_terminal_plan(handle)
            retiring, = self.base.glob('retiring-plan-*')
            self.assertEqual({p.name: p.read_bytes() for p in retiring.iterdir()}, before)
        with self.store.transaction() as recovery:
            stage.retire_terminal_plan(recovery)
            recovery.clear_finished(lambda _: True)


if __name__ == '__main__':
    unittest.main()
