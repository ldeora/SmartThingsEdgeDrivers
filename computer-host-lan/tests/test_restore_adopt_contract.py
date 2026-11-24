"""Wire/transition compatibility fixtures; no root, systemd or production writes."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import installer_root as old_request
import transaction_journal as old_journal
import restore_adopt_contract as contract

SOURCE = 'snapshot-historical'
BEFORE = 'snapshot-current'
H = 'a' * 64
RESTORE = dict(schema_version=3, action='restore', snapshot_name=SOURCE,
               confirmation='RESTORE')
ADOPT = dict(schema_version=3, action='adopt', confirmation='ADOPT',
             retained_protocol='v2', power='disable', wol_interface=None)
RESTORE_EVIDENCE = dict(source_receipt_sha256=H, source_manifest_sha256=H,
                        release_manifest_sha256=H, staged_plan_sha256=H,
                        agent_version='0.4.6-rc.2', renderer='v2_fixed_plan_1')
ADOPT_EVIDENCE = dict(payload_manifest_sha256=H, staged_plan_sha256=H,
                      agent_version='0.4.6-rc.2', retained_layout='verified',
                      service_state='verified_absent', pre_begin_journal='verified_empty')


def wire(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':')).encode('ascii')


def initial(intent):
    return dict(schema=2, transaction_id='a' * 32, operation=intent['action'],
                phase='INSPECTED', snapshot_name=None, before_receipt_sha256=None,
                intent=dict(intent), evidence=None)


def stages(intent):
    evidence = RESTORE_EVIDENCE if intent['action'] == 'restore' else ADOPT_EVIDENCE
    records = [initial(intent)]
    records.append(dict(records[-1], phase='STAGED', evidence=dict(evidence)))
    records.append(dict(records[-1], phase='SNAPSHOTTED', snapshot_name=BEFORE,
                        before_receipt_sha256=H))
    for phase in ('APPLYING', 'ACTIVATING', 'VERIFYING', 'COMMITTED'):
        records.append(dict(records[-1], phase=phase))
    return records


class RequestContractTests(unittest.TestCase):
    def test_new_intents_exact_and_old_decoder_refuses(self):
        for intent in (RESTORE, ADOPT, dict(ADOPT, power='enable', wol_interface='eth0')):
            with self.subTest(action=intent['action']):
                self.assertEqual(contract.decode_request(wire(intent)), intent)
                with self.assertRaises(old_request.RequestError):
                    old_request.parse_request(wire(intent))

    def test_old_request_grammar_preserved(self):
        cases = [dict(schema_version=1, action=action)
                 for action in ('status', 'recover')]
        cases += [dict(schema_version=1, action=action, source='/fixture/source',
                       power='preserve', wol_interface=None)
                  for action in ('install', 'upgrade', 'repair')]
        cases.append(dict(schema_version=2, action='uninstall'))
        for data in cases:
            raw = wire(data)
            self.assertEqual(contract.decode_request(raw), dict(
                schema_version=data['schema_version'], **old_request.parse_request(raw)))

    def test_malformed_intents_and_untrusted_inputs_rejected(self):
        cases = [
            dict(RESTORE, schema_version=True), dict(RESTORE, schema_version=2),
            dict(RESTORE, snapshot_name='/tmp/snapshot-abcdefgh'),
            dict(RESTORE, snapshot_name='../snapshot-abcdefgh'),
            dict(RESTORE, snapshot_name='snapshot-x'),
            dict(RESTORE, confirmation='ADOPT'), dict(RESTORE, source='/tmp/source'),
            dict(RESTORE, release_manifest_sha256=H),
            dict(ADOPT, retained_protocol='v1'), dict(ADOPT, confirmation=True),
            dict(ADOPT, power='preserve'), dict(ADOPT, wol_interface='..'),
            dict(ADOPT, wol_interface='eth0;id'), dict(ADOPT, wol_interface=42),
            dict(ADOPT, control_key='private'), dict(ADOPT, identity='private'),
            dict(ADOPT, snapshot_name=SOURCE),
        ]
        for data in cases:
            with self.subTest(action=data['action'], keys=sorted(data)):
                with self.assertRaises(contract.ContractError):
                    contract.decode_request(wire(data))
        for raw in (b'{"schema_version":3,"schema_version":3,"action":"restore"}',
                    b'null', b'[]', b'{' + b'a' * 4096 + b'}',
                    b'[' * 1000 + b']' * 1000):
            with self.assertRaises(contract.ContractError):
                contract.decode_request(raw)


class JournalContractTests(unittest.TestCase):
    def test_valid_forward_transitions_and_recovery_classification(self):
        for intent in (RESTORE, ADOPT):
            records = stages(intent)
            for current, following in zip(records, records[1:]):
                self.assertEqual(contract.validate_transition(current, following), following)
            for index, record in enumerate(records):
                self.assertEqual(contract.decode_journal(wire(record)), record)
                action = ('abort_before_apply' if index < 3 else
                          'rollback_before_state' if index < 6 else 'terminal_cleanup')
                self.assertEqual(contract.recovery_disposition(wire(record)),
                                 contract.RecoveryDisposition(intent['action'] + '_v2', action))

    def test_abort_and_rollback_require_correct_phase_and_immutable_evidence(self):
        for intent in (RESTORE, ADOPT):
            records = stages(intent)
            for index, record in enumerate(records[:-1]):
                accepted = 'ABORTED' if index < 3 else 'ROLLED_BACK'
                refused = 'ROLLED_BACK' if index < 3 else 'ABORTED'
                terminal = dict(record, phase=accepted)
                self.assertEqual(contract.validate_transition(record, terminal), terminal)
                self.assertEqual(contract.recovery_disposition(wire(terminal)).action,
                                 'terminal_cleanup')
                with self.assertRaises(contract.ContractError):
                    contract.validate_transition(record, dict(record, phase=refused))
                with self.assertRaises(contract.ContractError):
                    contract.validate_transition(terminal, terminal)

    def test_invalid_evidence_and_snapshot_pairs(self):
        r = stages(RESTORE)
        a = stages(ADOPT)
        cases = [
            dict(r[0], evidence=RESTORE_EVIDENCE),
            dict(r[1], evidence=None), dict(r[1], snapshot_name=BEFORE),
            dict(r[2], snapshot_name=SOURCE),
            dict(r[2], before_receipt_sha256=None),
            dict(r[2], snapshot_name=None, before_receipt_sha256=None),
            dict(r[2], evidence=dict(RESTORE_EVIDENCE, renderer='unknown')),
            dict(r[2], evidence=dict(RESTORE_EVIDENCE, source_receipt_sha256=True)),
            dict(r[2], evidence=dict(RESTORE_EVIDENCE, control_key=H)),
            dict(a[2], evidence=dict(ADOPT_EVIDENCE, pre_begin_journal='unknown')),
            dict(a[2], evidence=dict(ADOPT_EVIDENCE, retained_layout='not_verified')),
            dict(a[2], intent=RESTORE), dict(a[2], schema=True),
            dict(a[2], operation='upgrade'), dict(a[2], phase=[]),
            dict(a[2], phase='ABORTED', evidence=None),
        ]
        for i, record in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(contract.ContractError):
                contract.decode_journal(wire(record))

    def test_transition_refuses_rebinding_or_skipping(self):
        r = stages(RESTORE)
        a = stages(ADOPT)
        cases = [
            (r[0], r[2]), (r[2], r[1]),
            (r[1], dict(r[2], transaction_id='b' * 32)),
            (r[1], dict(r[2], intent=dict(RESTORE, snapshot_name='snapshot-otherold'))),
            (r[2], dict(r[3], snapshot_name='snapshot-othernew')),
            (r[2], dict(r[3], before_receipt_sha256='b' * 64)),
            (r[2], dict(r[3], evidence=dict(RESTORE_EVIDENCE, staged_plan_sha256='b' * 64))),
            (a[0], dict(a[1], intent=dict(ADOPT, power='enable'))),
            (a[0], dict(a[1], intent=dict(ADOPT, wol_interface='eth0'))),
            (a[1], dict(a[2], phase='ABORTED')),  # cannot add a snapshot on abort
            (a[6], a[6]),
        ]
        for i, (old, new) in enumerate(cases):
            before = copy.deepcopy((old, new))
            with self.subTest(case=i), self.assertRaises(contract.ContractError):
                contract.validate_transition(old, new)
            self.assertEqual((old, new), before)

    def test_journal_wire_bounds_and_duplicate_nested_keys(self):
        raw = wire(stages(RESTORE)[2])
        self.assertLess(len(raw), old_journal._MAX_BYTES)
        bad = raw.replace(b'"confirmation":"RESTORE"',
                          b'"confirmation":"RESTORE","confirmation":"RESTORE"')
        for data in (bad, b'{' + b'a' * old_journal._MAX_BYTES + b'}', b'[]'):
            with self.assertRaises(contract.ContractError):
                contract.decode_journal(data)


class ExistingHelperCompatibilityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = old_journal.ProtectedJournal(root=self.root, owner_uid=os.geteuid())
        self.path = self.root / 'var/backups/linux-host-agent/wizard-transactions/journal.json'

    def test_current_journal_writer_readable_by_candidate_codec(self):
        # Real existing durable writer/reader, disposable filesystem only.
        for operation in ('install', 'upgrade', 'repair', 'uninstall'):
            with self.store.begin(operation) as handle:
                raw = self.path.read_bytes()
                self.assertEqual(contract.decode_journal(raw), handle._record())
                self.assertEqual(contract.recovery_disposition(raw),
                                 contract.RecoveryDisposition('legacy_v1', 'abort_before_apply'))
                handle.advance('INSPECTED', 'STAGED')
                handle.advance('STAGED', 'SNAPSHOTTED', snapshot_name=BEFORE)
                handle.advance('SNAPSHOTTED', 'APPLYING')
                raw = self.path.read_bytes()
                self.assertEqual(contract.decode_journal(raw), handle._record())
                self.assertEqual(contract.recovery_disposition(raw).action,
                                 'rollback_before_state')
                handle.advance('APPLYING', 'ACTIVATING')
                handle.advance('ACTIVATING', 'VERIFYING')
                handle.advance('VERIFYING', 'COMMITTED')
                raw = self.path.read_bytes()
                self.assertEqual(contract.recovery_disposition(raw).action, 'terminal_cleanup')
                handle.clear_finished()

    def test_current_journal_apis_preserve_exact_valid_v2_records(self):
        with self.store.begin('install'):
            pass
        # These are the actual proposed records, not merely a v1 record
        # with an unknown operation substituted. Old APIs must refuse all
        # phases, including cleanup and reaping of terminal records.
        for intent in (RESTORE, ADOPT):
            records = stages(intent)
            records += [dict(records[0], phase='ABORTED'),
                        dict(records[3], phase='ROLLED_BACK')]
            for record in records:
                with self.subTest(operation=record['operation'], phase=record['phase']):
                    raw = wire(record)
                    self.assertEqual(contract.decode_journal(raw), record)
                    self.path.write_bytes(raw)
                    for call in (self.store.public_status, self.store.resume_recovery,
                                 self.store.resume_finished_cleanup, self.store.finish_terminal,
                                 lambda: self.store.begin('install')):
                        with self.assertRaises(old_journal.UnsafeJournal):
                            call()
                        self.assertEqual(self.path.read_bytes(), raw)


    def test_embedded_old_helper_modules_refuse_new_wire_and_preserve_journal(self):
        # Execute the actual embedded Python modules in a fresh isolated
        # interpreter, not source checkout imports or a mock decoder.
        # The harness deliberately does not invoke installed-root main()
        # (which requires the real fixed trusted directory and root).
        bundle = ROOT / 'linux-installer/bundle/scripts'
        script = """
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import installer_root
import transaction_journal
root = Path(sys.argv[2])
assert Path(installer_root.__file__).parent == Path(sys.argv[1])
assert Path(transaction_journal.__file__).parent == Path(sys.argv[1])
payload = json.load(sys.stdin)
for intent in payload['intents']:
    try:
        installer_root.parse_request(json.dumps(intent).encode('ascii'))
    except installer_root.RequestError:
        pass
    else:
        raise AssertionError('embedded helper accepted future intent')
store = transaction_journal.ProtectedJournal(root=root, owner_uid=os.geteuid())
path = root / 'var/backups/linux-host-agent/wizard-transactions/journal.json'
with store.begin('install'):
    pass
for record in payload['records']:
    before = json.dumps(record, sort_keys=True).encode('ascii')
    path.write_bytes(before)
    for call in (store.public_status, store.resume_recovery,
                 store.resume_finished_cleanup, store.finish_terminal,
                 lambda: store.begin('repair')):
        try:
            call()
        except transaction_journal.UnsafeJournal:
            pass
        else:
            raise AssertionError('embedded helper accepted future journal')
        assert path.read_bytes() == before
print('refused')
"""
        records = []
        for intent in (RESTORE, ADOPT):
            candidate = stages(intent)
            records.extend((candidate[0], candidate[3], candidate[-1],
                            dict(candidate[3], phase='ROLLED_BACK')))
        run = subprocess.run(
            [sys.executable, '-I', '-S', '-B', '-c', script,
             str(bundle), str(self.root)],
            input=wire({'intents': [RESTORE, ADOPT], 'records': records}),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8', 'replace'))
        self.assertEqual(run.stdout, b'refused\n')

if __name__ == '__main__':
    unittest.main()
