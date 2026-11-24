"""Concrete fixture evidence checks, not privileged execution authorization.

The controller still needs trusted release/eligibility evidence, actual
systemd checks, owner-marker policy and private credential continuity.
These helpers exercise the exact stage and before-state bindings using
the actual protected filesystem primitives. No live systemd or apply.
"""
from __future__ import annotations

import restore_adopt_before as before
import restore_adopt_journal as journal
import restore_adopt_stage as stage


def _check_expected_plan(handle, files, services, *, digest, initial):
    # Expected bytes must come from the independent trusted caller, not
    # by deriving them from the stage that is being checked.
    raw, _ = stage._encode_plan(handle.record(), files, services)
    if stage._hash(raw) != digest:
        raise stage.PlanError('independent_plan_mismatch')
    pinned = stage.read_plan(handle, initial_digest=digest if initial else None)
    if pinned.digest != digest:
        raise stage.PlanError('independent_plan_mismatch')
    return pinned


def bind_stage(handle, *, digest, evidence, expected_files, expected_services):
    """Bind a verified stage at STAGED; source trust remains a caller duty."""
    if handle.record()['phase'] != 'INSPECTED':
        raise stage.PlanError('stage_binding_requires_inspected')
    if evidence.get('staged_plan_sha256') != digest:
        raise stage.PlanError('stage_evidence_mismatch')

    def verify(proposed):
        _check_expected_plan(handle, expected_files, expected_services,
                             digest=proposed['evidence']['staged_plan_sha256'], initial=True)
        return True

    handle.advance('STAGED', evidence=evidence, verify=verify)


def bind_before(handle, capture, observer):
    """Bind only the new receipt-bound snapshot that matches current state."""
    if handle.record()['phase'] != 'STAGED':
        raise before.BeforeStateError('before_binding_requires_staged')

    def verify(proposed):
        pinned = before.read_before(handle, proposed=capture)
        return (pinned.snapshot_name == proposed['snapshot_name'] and
                pinned.receipt_sha256 == proposed['before_receipt_sha256'] and
                before.matches_current(handle, pinned, observer))

    handle.advance('SNAPSHOTTED', snapshot_name=capture.snapshot_name,
                   before_receipt_sha256=capture.receipt_sha256, verify=verify)


def check_apply_evidence(handle, *, expected_files, expected_services, observer):
    """Read-only fixture preapply check, not permission to enter APPLYING.

    Production also needs a fresh eligibility/consent/identity check.
    Return pinned before-state and plan bytes; never write managed files.
    """
    record = handle.record()
    handle._clean()
    if handle._recovering or record['phase'] != 'SNAPSHOTTED':
        raise before.BeforeStateError('apply_evidence_requires_forward_snapshot')
    pinned_plan = _check_expected_plan(
        handle, expected_files, expected_services,
        digest=record['evidence']['staged_plan_sha256'], initial=False)
    pinned_before = before.read_before(handle)
    if not before.matches_current(handle, pinned_before, observer):
        raise before.BeforeStateError('current_before_state_mismatch')
    return pinned_plan, pinned_before


def check_rollback_evidence(handle, observer):
    """Compare restored fixture files and observed services against receipt.

    Does not mark ROLLED_BACK: real recovery additionally requires owner
    marker, identity/key preservation and verified service observation.
    """
    record = handle.record()
    handle._clean()
    if record['phase'] not in ('APPLYING', 'ACTIVATING', 'VERIFYING'):
        raise before.BeforeStateError('rollback_evidence_requires_applied_phase')
    return before.matches_current(handle, before.read_before(handle), observer)
