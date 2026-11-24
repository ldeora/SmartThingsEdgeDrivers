"""Experimental restore/adopt request and journal wire contracts.

No production caller, privileged dispatch, journal writer, or helper promotion.
Validation proves structure and transition consistency, not authorization,
release authenticity, file integrity, service state, or successful recovery.
The existing installed helper must continue to reject these new versions.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

import installer_root as legacy_request
import transaction_journal as legacy_journal

_REQUEST_VERSION = 3
_JOURNAL_VERSION = 2
_OPERATIONS = frozenset(('restore', 'adopt'))
_PHASES = ('INSPECTED', 'STAGED', 'SNAPSHOTTED', 'APPLYING',
           'ACTIVATING', 'VERIFYING', 'COMMITTED')
_TERMINAL = frozenset(('ABORTED', 'ROLLED_BACK', 'COMMITTED'))
_NEEDS_BEFORE = frozenset(_PHASES[2:]) | {'ROLLED_BACK'}
_APPLIED = frozenset(('APPLYING', 'ACTIVATING', 'VERIFYING'))
# Keep the same wire bounds as the existing boundary. No credential
# bytes, private-state hashes, source paths, or arbitrary commands.
_MAX_REQUEST = legacy_request._MAX_REQUEST_BYTES
_MAX_JOURNAL = legacy_journal._MAX_BYTES
_RENDERER = 'v2_fixed_plan_1'


class ContractError(ValueError):
    """Fixed diagnostics only; never echo wire values or exception detail."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('duplicate_key')
        result[key] = value
    return result


def _decode(raw: bytes, limit: int) -> dict:
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ContractError('invalid_wire_length')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique)
    except (UnicodeError, ValueError, RecursionError):
        raise ContractError('invalid_wire_json') from None
    if type(data) is not dict:
        raise ContractError('invalid_wire_object')
    return data


def _match(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def _keys(value, keys):
    return type(value) is dict and set(value) == keys


def validate_new_intent(data: object) -> dict:
    """Validate a v3 request. Literal confirmation is intent, not authority."""
    if (type(data) is not dict or type(data.get('schema_version')) is not int or
            data['schema_version'] != _REQUEST_VERSION or
            type(data.get('action')) is not str or data['action'] not in _OPERATIONS):
        raise ContractError('unsupported_request')
    if data['action'] == 'restore':
        if (not _keys(data, {'schema_version', 'action', 'snapshot_name', 'confirmation'}) or
                data['confirmation'] != 'RESTORE' or
                not _match(data['snapshot_name'], legacy_journal._SNAPSHOT)):
            raise ContractError('invalid_restore_intent')
    else:
        if (not _keys(data, {'schema_version', 'action', 'confirmation',
                             'retained_protocol', 'power', 'wol_interface'}) or
                data['confirmation'] != 'ADOPT' or data['retained_protocol'] != 'v2' or
                type(data['power']) is not str or data['power'] not in ('enable', 'disable') or
                (data['wol_interface'] is not None and
                 (not _match(data['wol_interface'], legacy_request._NIC) or
                  data['wol_interface'] in ('.', '..')))):
            raise ContractError('invalid_adopt_intent')
    return dict(data)


def decode_request(raw: bytes) -> dict:
    """Candidate version-aware decoder; existing schemas retain their grammar."""
    data = _decode(raw, _MAX_REQUEST)
    version = data.get('schema_version')
    if type(version) is int and version in (1, 2):
        try:
            return dict(schema_version=version, **legacy_request.parse_request(raw))
        except (legacy_request.RequestError, RecursionError):
            raise ContractError('invalid_legacy_request') from None
    return validate_new_intent(data)


def _digest(value):
    return _match(value, legacy_request._SHA256)


def _validate_evidence(operation, evidence):
    # Digests bind root-produced evidence records to the durable intent.
    # This codec never reads those records or asserts that they are valid.
    if operation == 'restore':
        hashes = {'source_receipt_sha256', 'source_manifest_sha256',
                  'release_manifest_sha256', 'staged_plan_sha256'}
        if (not _keys(evidence, hashes | {'agent_version', 'renderer'}) or
                any(not _digest(evidence[key]) for key in hashes) or
                not _match(evidence['agent_version'], legacy_request._VERSION) or
                evidence['renderer'] != _RENDERER):
            raise ContractError('invalid_restore_evidence')
    else:
        hashes = {'payload_manifest_sha256', 'staged_plan_sha256'}
        if (not _keys(evidence, hashes | {'agent_version', 'retained_layout',
                                          'service_state', 'pre_begin_journal'}) or
                any(not _digest(evidence[key]) for key in hashes) or
                not _match(evidence['agent_version'], legacy_request._VERSION) or
                evidence['retained_layout'] != 'verified' or
                evidence['service_state'] != 'verified_absent' or
                evidence['pre_begin_journal'] != 'verified_empty'):
            raise ContractError('invalid_adopt_evidence')
    return dict(evidence)


def validate_record(data: object) -> dict:
    """Read legacy v1 unchanged, or validate a proposed v2 journal record.

    snapshot_name is exclusively the NEW current-before-state snapshot.
    Historical forward source belongs only to restore intent. The
    before-receipt digest binds the original snapshot metadata and hashes
    to this transaction; recovery must verify the actual receipt and bytes.
    """
    if type(data) is not dict or type(data.get('schema')) is not int:
        raise ContractError('unsupported_journal')
    if data['schema'] == 1:
        try:
            return dict(legacy_journal._validate(data))
        except legacy_journal.UnsafeJournal:
            raise ContractError('invalid_legacy_journal') from None
    if (data['schema'] != _JOURNAL_VERSION or
            not _keys(data, {'schema', 'transaction_id', 'operation', 'phase',
                             'snapshot_name', 'before_receipt_sha256',
                             'intent', 'evidence'}) or
            not _match(data['transaction_id'], legacy_journal._TXID) or
            type(data['operation']) is not str or data['operation'] not in _OPERATIONS or
            type(data['phase']) is not str or
            data['phase'] not in set(_PHASES) | _TERMINAL):
        raise ContractError('unsupported_journal')
    operation = data['operation']
    phase = data['phase']
    intent = validate_new_intent(data['intent'])
    if intent['action'] != operation:
        raise ContractError('intent_operation_mismatch')
    snapshot, before = data['snapshot_name'], data['before_receipt_sha256']
    if ((snapshot is None) != (before is None) or
            (snapshot is not None and
             (not _match(snapshot, legacy_journal._SNAPSHOT) or not _digest(before))) or
            (operation == 'restore' and snapshot == intent['snapshot_name'])):
        raise ContractError('invalid_before_state')
    if ((phase in ('INSPECTED', 'STAGED') and snapshot is not None) or
            (phase in _NEEDS_BEFORE and snapshot is None)):
        raise ContractError('invalid_before_state_phase')
    evidence = data['evidence']
    if (phase == 'INSPECTED' and evidence is not None or
            phase not in ('INSPECTED', 'ABORTED') and evidence is None or
            snapshot is not None and evidence is None):
        raise ContractError('invalid_evidence_phase')
    if evidence is not None:
        evidence = _validate_evidence(operation, evidence)
    return dict(data, intent=intent, evidence=evidence)


def decode_journal(raw: bytes) -> dict:
    return validate_record(_decode(raw, _MAX_JOURNAL))


def validate_transition(old: object, new: object) -> dict:
    """Candidate v2 transition guard, not a persistence or recovery API."""
    old = validate_record(old)
    new = validate_record(new)
    if old['schema'] != _JOURNAL_VERSION or new['schema'] != _JOURNAL_VERSION:
        raise ContractError('unsupported_transition_schema')
    if any(old[key] != new[key] for key in ('schema', 'transaction_id', 'operation', 'intent')):
        raise ContractError('immutable_intent_changed')
    first, second = old['phase'], new['phase']
    if first in _TERMINAL:
        raise ContractError('terminal_transition')
    if second == 'ABORTED':
        allowed = first in ('INSPECTED', 'STAGED', 'SNAPSHOTTED')
    elif second == 'ROLLED_BACK':
        allowed = first in _APPLIED
    else:
        allowed = second in _PHASES and _PHASES.index(second) == _PHASES.index(first) + 1
    if not allowed:
        raise ContractError('invalid_transition')
    if (first, second) != ('INSPECTED', 'STAGED') and old['evidence'] != new['evidence']:
        raise ContractError('immutable_evidence_changed')
    if (first, second) != ('STAGED', 'SNAPSHOTTED') and any(
            old[key] != new[key] for key in ('snapshot_name', 'before_receipt_sha256')):
        raise ContractError('immutable_before_state_changed')
    return new


@dataclass(frozen=True)
class RecoveryDisposition:
    contract: str
    action: str


def recovery_disposition(raw: bytes) -> RecoveryDisposition:
    """Classify only; never route a v2 record into the v1 recovery engine.

    Even a terminal record needs compatible cleanup. Never resume forward
    historical restore/adoption from a journal or claim a clean status.
    """
    record = decode_journal(raw)
    contract = ('legacy_v1' if record['schema'] == 1
                else record['operation'] + '_v2')
    phase = record['phase']
    if phase in _TERMINAL:
        action = 'terminal_cleanup'
    elif phase in _APPLIED:
        action = 'rollback_before_state'
    else:
        action = 'abort_before_apply'
    return RecoveryDisposition(contract, action)
