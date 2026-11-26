"""Historical candidate fixtures; no privileged restore or real host reads."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_core as core
import historical_snapshot as historical


class HistoricalCandidateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.transaction = core.InstallTransaction(self.root)
        self.contents = {
            core.APP_FILES[0]: b'PROTOCOL = "computer-host-agent"\nVERSION = "0.4.6"\n',
            core.APP_FILES[1]: b'# fixture power helper\n',
            **{path: b'# fixture unit\n' for path in core.SYSTEMD_PATHS},
            core.POWER_DROPIN: b'# fixture power drop-in\n',
        }
        changes = []
        for path in sorted(core.MANAGED_PATHS):
            content = self.contents.get(path)
            mode = 0o755 if path in core.APP_FILES else 0o644
            changes.append(core.Change(path, content, mode))
        self.transaction.apply(changes)
        self.backup = self.transaction.snapshot(changes, previous={
            'first_install': False, 'agent_active': True, 'agent_enabled': True,
            'socket_active': True, 'socket_enabled': True,
            'newly_enabled_power': False,
        })
        self.manifest = self.backup / 'manifest.json'
        self.expected_manifest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        self.expected_files = {path: hashlib.sha256(content).hexdigest()
                               for path, content in self.contents.items()}

    def inspect(self, **overrides):
        # Expectations are synthetic fixture data; production must obtain
        # independent authenticated evidence, not calculate it here.
        args = dict(expected_manifest_sha256=self.expected_manifest,
                    expected_file_hashes=self.expected_files,
                    expected_agent_version='0.4.6',
                    owner_uid=os.geteuid(), owner_gid=os.getegid())
        args.update(overrides)
        return historical.inspect_candidate(self.root, self.backup.name, **args)

    def rewrite(self, mutate):
        data = json.loads(self.manifest.read_text())
        mutate(data)
        self.manifest.write_text(json.dumps(data))
        self.expected_manifest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def agent_backup(self):
        records = json.loads(self.manifest.read_text())['items']
        return self.backup / next(item['file'] for item in records
                                  if item['path'] == core.APP_FILES[0])

    def local_inspect(self, name=None):
        return historical.inspect_local_backup(
            self.root, name or self.backup.name,
            owner_uid=os.geteuid(), owner_gid=os.getegid())

    def test_local_backup_selects_v2_and_binds_bytes(self):
        summary, _ = self.local_inspect()
        self.assertEqual(summary['version'], '0.4.6')
        self.assertEqual(summary['coverage'], 'complete')
        self.assertEqual(summary['power'], 'enabled')
        self.agent_backup().write_bytes(self.agent_backup().read_bytes() + b'# changed\n')
        self.assertNotEqual(self.local_inspect()[0]['digest'], summary['digest'])

    def test_local_backup_rejects_paths_legacy_modes_links_and_empty_sources(self):
        for name in ('../snapshot-abcdef', '/tmp/snapshot-abcdef', 'not-a-backup'):
            with self.assertRaises(historical.SnapshotEligibilityError):
                self.local_inspect(name)
        original = self.manifest.read_bytes()
        for mutate in (
                lambda data: data['previous'].update(first_install=True),
                lambda data: data['items'][0].update(mode=0o7777),
                lambda data: data.update(schema=True),
                lambda data: data.update(installer_protocol='v1')):
            self.manifest.write_bytes(original)
            self.rewrite(mutate)
            with self.assertRaises(historical.SnapshotEligibilityError):
                self.local_inspect()
        self.manifest.write_bytes(original)
        self.agent_backup().write_bytes(b'PROTOCOL = "linux-host-agent"\nVERSION = "0.4.6"\n')
        self.assertEqual(historical.list_local_backups(
            self.root, owner_uid=os.geteuid(), owner_gid=os.getegid()), [])
        self.agent_backup().write_bytes(self.contents[core.APP_FILES[0]])
        os.link(self.agent_backup(), self.backup / 'extra')
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.local_inspect()

    def test_complete_candidate_returns_pinned_bytes_without_writes(self):
        before = {p.name: p.read_bytes() for p in self.backup.iterdir()}
        candidate = self.inspect()
        self.assertEqual(candidate.agent_version, '0.4.6')
        self.assertEqual({f.path: f.content for f in candidate.files},
                         {p: self.contents.get(p) for p in core.MANAGED_PATHS})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.backup.iterdir()})
        self.agent_backup().write_bytes(b'changed afterward')
        self.assertEqual(next(f.content for f in candidate.files
                              if f.path == core.APP_FILES[0]), self.contents[core.APP_FILES[0]])

    def test_untrusted_or_changed_manifest_and_file_are_refused(self):
        for overrides in (
                {'expected_manifest_sha256': '0' * 64},
                {'expected_file_hashes': {}},
                {'expected_agent_version': '0.4.5'}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(historical.SnapshotEligibilityError):
                    self.inspect(**overrides)
        self.agent_backup().write_bytes(b'PROTOCOL = "computer-host-agent"\nVERSION = "0.4.6"\n# changed')
        with self.assertRaisesRegex(historical.SnapshotEligibilityError, 'digest'):
            self.inspect()

    def test_partial_plan_and_legacy_or_broken_service_state_refused(self):
        original = self.manifest.read_bytes()
        for mutate in (
                lambda data: data['items'].pop(),
                lambda data: data['previous'].update(first_install=True),
                lambda data: data['previous'].update(agent_retry=True),
                lambda data: data['previous'].update(agent_active=1),
                lambda data: data['previous'].pop('socket_active'),
                lambda data: data.update(schema=True),
                lambda data: data['items'][0].update(mode=0o7777)):
            self.manifest.write_bytes(original)
            self.rewrite(mutate)
            with self.assertRaises(historical.SnapshotEligibilityError):
                self.inspect()

    def test_duplicate_manifest_key_refused_even_with_matching_digest(self):
        data = self.manifest.read_bytes()
        data = data.replace(b'"schema": 1', b'"schema": 1, "schema": 1', 1)
        self.manifest.write_bytes(data)
        self.expected_manifest = hashlib.sha256(data).hexdigest()
        with self.assertRaisesRegex(historical.SnapshotEligibilityError, 'duplicate'):
            self.inspect()

    def test_extra_entry_and_hardlink_refused(self):
        extra = self.backup / 'extra'
        extra.write_bytes(b'extra')
        with self.assertRaisesRegex(historical.SnapshotEligibilityError, 'entry'):
            self.inspect()
        extra.unlink()
        os.link(self.agent_backup(), self.root / 'external-link')
        with self.assertRaisesRegex(historical.SnapshotEligibilityError, 'unsafe'):
            self.inspect()

    def test_linked_parent_and_unsafe_mode_refused(self):
        base = self.backup.parent
        original = base.with_name('renamed')
        base.rename(original)
        base.symlink_to(original, target_is_directory=True)
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect()
        base.unlink()
        original.rename(base)
        self.agent_backup().chmod(0o777)
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect()

    def test_invalid_snapshot_identifier_never_traverses(self):
        for name in ('../snapshot-abcdef', '/snapshot-abcdef', 'snapshot-x'):
            with self.assertRaisesRegex(historical.SnapshotEligibilityError, 'invalid_candidate'):
                historical.inspect_candidate(self.root, name,
                    expected_manifest_sha256=self.expected_manifest,
                    expected_file_hashes=self.expected_files,
                    expected_agent_version='0.4.6')

    def write_receipt(self, **updates):
        manifest = json.loads(self.manifest.read_text())
        receipt = {
            'schema_version': 1, 'origin': 'protected_before_state',
            'snapshot_name': self.backup.name, 'transaction_id': 'a' * 32,
            'operation': 'upgrade', 'capture_phase': 'STAGED',
            'manifest_sha256': self.expected_manifest,
            'file_sha256': self.expected_files,
            'copy_modes': {item['path']: (self.backup / item['file']).stat().st_mode & 0o7777
                           for item in manifest['items'] if item['existed']},
            'coverage': 'complete',
            'captured_paths': sorted(core.MANAGED_PATHS), 'agent_version': '0.4.6',
            'service_observation': 'protected_capture_previous',
            'previous': manifest['previous'], 'release_authenticity': 'not_verified',
        }
        receipt.update(updates)
        path = self.backup.parent / ('.' + self.backup.name + '.protected.json')
        path.write_text(json.dumps(receipt))
        path.chmod(0o600)
        return path

    def inspect_protected(self, **updates):
        args = dict(expected_file_hashes=self.expected_files,
                    expected_agent_version='0.4.6',
                    owner_uid=os.geteuid(), owner_gid=os.getegid())
        args.update(updates)
        return historical.inspect_protected_candidate(self.root, self.backup.name, **args)

    def test_protected_candidate_requires_receipt_and_independent_hashes(self):
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect_protected()
        self.write_receipt()
        self.assertEqual(self.inspect_protected(), self.inspect())
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect_protected(expected_file_hashes={})
        self.agent_backup().write_bytes(b'changed')
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect_protected()

    def test_protected_receipt_rejects_mismatch_or_unsupported_capture(self):
        for updates in (
                {'coverage': 'partial'}, {'schema_version': True},
                {'origin': 'legacy'}, {'snapshot_name': 'snapshot-other'},
                {'operation': 'install'}, {'capture_phase': 'COMMITTED'},
                {'release_authenticity': 'verified'}, {'transaction_id': 'wrong'},
                {'previous': {'agent_active': False}},
                {'copy_modes': {}},
                {'copy_modes': {core.APP_FILES[0]: True}}):
            with self.subTest(updates=updates):
                self.write_receipt(**updates)
                with self.assertRaises(historical.SnapshotEligibilityError):
                    self.inspect_protected()

    def test_capture_of_unsafe_mode_remains_ineligible_after_copy_chmod(self):
        # The receipt preserves the observed mode even when the copy
        # is subsequently repaired. Content digests alone are insufficient.
        copy = self.agent_backup()
        copy.chmod(0o775)
        self.write_receipt()
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect_protected()
        copy.chmod(0o755)
        with self.assertRaisesRegex(historical.SnapshotEligibilityError,
                                    'protected_receipt_mismatch'):
            self.inspect_protected()

    def test_protected_receipt_rejects_links_and_permissions(self):
        receipt = self.write_receipt()
        receipt.chmod(0o644)
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect_protected()
        receipt.chmod(0o600)
        os.link(receipt, self.root / 'receipt-link')
        with self.assertRaises(historical.SnapshotEligibilityError):
            self.inspect_protected()


if __name__ == '__main__':
    unittest.main()
