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


if __name__ == '__main__':
    unittest.main()
