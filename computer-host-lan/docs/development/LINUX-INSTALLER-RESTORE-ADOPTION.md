# Protected historical restoration and retained-state adoption

**Proposed design for #101; no new privileged operation is implemented.**
Review separately before any change to the helper, journal or CLI. Existing
rc.2 shell commands remain unchanged. This is not persistent WOL work.

## Current evidence and constraints

- `install_core.run_cli --rollback` selects a direct child of the backup
  base, validates v2 backup provenance, acquires the shared lock, checks
  the protected journal and restores the old snapshot. It does not
  journal the current before-state. Its service observations are legacy
  booleans, and its restoration does not perform the protected runtime
  verification. It can operate when current agent bytes are damaged.
- Schema-1 snapshots record allowlisted paths, existence, saved content,
  mode, uid/gid and previous service state. They do not provide an
  independent cryptographic release provenance or a content hash manifest.
  `validate_v2_backup` establishes v2/empty-agent provenance for the
  existing restore path, not a general authorization to run historical code.
- Protected `InstallerBackend._restore_snapshot` is specifically for
  undoing a journal-bound transaction. Recovery calls it with a special
  first-install ownership exception. The exception must never authorize
  a user-selected historical snapshot.
- `require_v2_or_clean(..., adopt_retained_state=True)` accepts only the
  orphan-state-only layout with no managed files and no owner record.
  This is a shape test, not proof that the private ID/key belongs to v2.
- `write_owner_record` retains v2 intent across uninstall and failed
  activation/rollback. It creates the folder and marker separately.
  A crash after mkdir or partial marker write is not equivalent to a
  valid v2 marker. Do not make adoption an unjournaled preliminary step.

## A. Historical snapshot restoration

Proposed CLI: `cli restore --snapshot snapshot-NAME --confirm RESTORE`.
The exact syntax, request version and output schema require review.
Never accept absolute paths, parent traversal, arbitrary source bytes,
arbitrary Python or additional service names through the privileged
request. An identifier selects only one root-owned direct child of the
fixed backup namespace. A future listing operation may expose safe
identifiers and sanitized eligibility, not snapshot contents or state
secrets; this PR adds neither operation.

A historical restore is a **new forward transaction**. Its source is
the selected historical snapshot; its rollback source is a **different,
new snapshot** of current state. The journal's snapshot_name must refer
to the latter, never the selected old snapshot. Recovery never repeats
the historical forward operation.

| Phase | Proposed restore semantics |
| --- | --- |
| INSPECTED | Lock, reconcile helper eligibility, reject outstanding journal, check current state and target snapshot |
| STAGED | Pin and validate bounded historical bytes, metadata and service-state interpretation; bind to transaction |
| SNAPSHOTTED | Save and durably sync complete current before-state for all touched targets |
| APPLYING | Quiesce affected units; restore fixed files with reviewed modes/ownership |
| ACTIVATING | Reload units, restore eligible recorded service configuration and state |
| VERIFYING | Check files, enablement, runtime and retained identity when applicable |
| COMMITTED | Only verified success; terminal cleanup may be retried |

Before APPLYING, interruption aborts without managed mutation; after
APPLYING, restore the new before-state via the protected recovery path.
If the current layout is unknown, v1, partially installed or has
unsafe managed targets, fail before mutation in the initial protected
implementation. Supporting repair of a damaged current installation
requires separately reviewed rollback evidence and explicit authorization;
the legacy command's broader behavior is not automatically inherited.

### Snapshot eligibility and compatibility

First increment should accept only snapshots with complete, strictly
validated metadata from a supported protected engine. An existing
schema-1 snapshot with legacy boolean service state is not automatically
eligible. Distinguish absent units from inactive/disabled, reject unsafe
or inconsistent state, unknown keys, duplicate paths, invalid mode/uid/gid,
missing/extra files, symlinks and unexpected links, and enforce bounded
sizes and a fixed managed file set. Resolve protected directories from
trusted descriptors and pin bytes used for restoration. Do not read
or return private ID or token from snapshot contents; those are not
managed snapshot targets. Establish policy for first-install/empty
snapshots, stopped agents and partial old plans before allowing them.
Default initial refusal is safer than fabricating absent file/service
records. Do not invoke historical code just because its file contains
the v2 protocol marker: determine supported version and trusted
provenance/compatibility, including rollback to an older API/runtime.
A new versioned snapshot manifest with hashes and explicit origin/service
metadata is a candidate, not yet an accepted format. No retroactive
authenticity assertion for old backups.

### Recovery and protocol compatibility

Existing journal operation enum is install/upgrade/repair/uninstall.
Adding restore requires coordinated journal decoding, helper promotion,
status, recovery, cleanup and CLI result support. An older helper must
not reinterpret a restore journal or replace the new helper underneath
it. Review interrupted helper promotion and old-client behavior; unknown
journal operation must fail closed rather than imply a clean journal.
Keep the old schema-1/2 operations and recovery compatibility.
Use an independent forward-restore function; share restoration primitives,
but do not call mark_rolled_back for a successful historical restore.
Test preapply abort, every applied phase, failure restoring services,
directory sync failure and explicit retry, terminal cleanup and no
automatic replay. Check current retained ID/key remains unchanged;
no arbitrary service mutations or network/power action.

## B. Explicit retained-state adoption

Proposed separate install-like intent with literal adoption confirmation
(e.g. `cli adopt --confirm ADOPT`); exact schema and options require
review. Not a generic force flag or automatic response to adoption_required.
The operator independently establishes the state is from a prior v2
installation. An ID or key that has a plausible format does not prove
protocol provenance. No v1 migration. No raw identity/key in CLI or logs.

Under the shared lock and before managed mutation, recheck that every
managed file is absent, no valid/partial/conflicting owner directory
exists, no journal is outstanding, and the retained state directory
and private entries meet ownership, mode, type and path-safety rules.
Check actual service-account ownership (missing/reused account must be
handled explicitly, not guessed), orphan service enablement, valid
canonical saved UUID and acceptable private-key state. Neither change
ownership of private files nor generate replacement identity/token
to make an unsafe state pass. A missing key/ID or ambiguous metadata
requires explicit reviewed eligibility policy; refuse by default.

Prefer a single journaled adoption-and-install operation, not a separate
untracked owner-marker write followed by ordinary install. Validate
trusted payload and before-state, then durably record APPLYING before
writing the marker, creating any account or modifying managed files.
Persist evidence of the specific authorized adoption intent, independent
of the user-selected snapshot and the special fresh-install recovery
exception. Decide and test what happens if adoption succeeds but agent
activation fails: retained v2 intent may survive only if the explicit
authorization and eligible evidence have been durably established.
A failed preapply adoption must leave no v2 marker. Make owner-marker
publication crash-safe (including parent directory entries), or document
a protected, deterministic repair path for an interrupted mkdir/write.
Never mark an ambiguous partial marker as valid simply to unblock recovery.

For existing v2 retained state with a valid marker, normal reinstall
remains the path. Adoption must refuse it, as well as any current v1,
mixed layout, surviving managed files, symlinks, unsafe state/owner
metadata and active/incomplete journal. Identity preservation must be
verified after activation where applicable; key equality is a separate
claim, not derived from UUID. Do not return private data.

## Implementation order and acceptance

1. Specify strict historical snapshot eligibility and provenance/version
   contract, before exposing a privileged restore action. Design safe
   ownership marker publication/reconciliation and adoption eligibility
   separately, without calling either from a live installer.
2. Review protocol/journal compatibility and recovery routing. Add
   tests for wrong schemas, old helpers, stale state, concurrent requests,
   interrupted helper promotion and lock ordering.
3. Implement adoption and restore in independent reviewable PRs with
   positive/negative fixture tests and failure injection. No compatibility
   wrapper may silently call the legacy modifying engine.
4. Supervised physical acceptance on a reversible host, with verified
   release executable (#84), retained identity/key evidence kept private,
   clean journal and correct service states. Include interrupted recovery
   evidence; ordinary reboot is not proof of sudden power-loss durability.

This document does not authorize live changes, historical recovery of
an actual host, or deployment of the development Go installer.
