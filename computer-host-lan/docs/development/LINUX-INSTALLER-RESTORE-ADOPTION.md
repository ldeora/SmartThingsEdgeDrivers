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

## Primitive implementation status

The first safety increment implements two independent pieces:

- The shared v2 marker writer now prepares a complete sibling directory
  with the fixed marker, syncs marker and directory, publishes it by
  rename under the existing shared lock, and syncs all fixed ancestors.
  Existing valid markers are synced again on retry. Root-owned,
  non-writable, no-follow directory ancestry is required. This addresses
  publication, not authorization: existing installation/recovery callers
  retain their original consent rules. An incomplete final directory
  from an older writer is still refused; an interrupted new writer may
  leave an ignored randomly named sibling. No automatic scavenging or
  promotion of abandoned siblings. Do not remove them without separate
  administrator inspection while no installation is active.
- Experimental `scripts/historical_snapshot.py` inspects only a complete
  installed-state schema-1 candidate against independently supplied
  expected manifest/file SHA-256 values and agent version. It opens fixed
  protected directory components without following links, bounds reads,
  rejects ambiguous metadata and extra/linked entries, and returns
  immutable bytes rather than a path to reread. It does not distinguish
  legacy boolean service observations from identically shaped protected
  observations. The authenticated origin/service-state evidence and
  version-compatibility policy must therefore be supplied by a future
  reviewed trust mechanism. Digests calculated from the candidate itself
  do not establish that evidence. No production caller, packaging change,
  new manifest writer or restore eligibility grant exists. Initial tests
  use synthetic expectations only.

The new marker publication closes the normal mkdir/partial-write window
at the final path. It is not a physical power-loss durability claim.
It does not yet implement explicit adoption intent in the journal or
reconcile old incomplete markers. Historical restore and adoption remain
unavailable through the Go helper and CLI.

## Protected capture records and orphan-state inspection

The protected controller now writes a separate schema-version-1 receipt
`.snapshot-NAME.protected.json` directly in the private backup base,
not inside the schema-1 snapshot. The protected writer issues it after
syncing the snapshot and before recording SNAPSHOTTED, with the shared
installer and journal locks held. It records local capture origin,
transaction/operation, manifest digest, hashes and observed copy modes of
present captured files, captured path coverage, observed old agent VERSION (or null), and the
actual protected capture_previous result, including retry flags when
present. It explicitly says release authenticity not_verified. A receipt
is not evidence of a committed transaction, verified historical runtime,
or publisher authentication. No legacy snapshot is retroactively certified.

The existing rollback manifest, file scope and recovery reader are unchanged.
Snapshot copies may preserve damaged installed permissions (for example a
group-writable Avahi service). Capture records those modes without refusing
repair solely because of the mode. The private snapshot directory, manifest
and receipt still require protected permissions; copies must remain bounded,
stable, regular, single-link and owned by the expected installer owner.
Historical eligibility independently requires the exact safe installed and
copy modes, consistent with the recorded capture modes. A later chmod of a
backup copy cannot make an unsafe capture eligible.
Ordinary upgrades can have partial plans because optional files are retained
untouched; complete historical eligibility requires every MANAGED_PATHS
entry, including explicit absence for optional files. Complete coverage is
not sufficient: required installed files, strict metadata, supported
service-state representation and independent installed-byte/version
expectations must also pass. A receipt reader requires the complete protected
capture and verifies the original manifest and pinned bytes using those
independent expectations. Hashes of unrendered release templates alone
do not authenticate rendered units. A trusted source for installed-byte
expectations and compatibility policy still needs implementation.

The receipt is mode 0600, created and synced before non-replacing
publication and ancestor synchronization. Publication or validation
failure aborts before managed mutation. A crash can leave an ignored
temporary .snapshot-provenance-<hex> receipt or an extra hard link;
historical inspection refuses unsafe receipts, while original recovery
remains independent of them. Cleanup of abandoned receipts and ownership
marker siblings is deferred to a separate, lock-protected review; do not
automatically remove or promote them. No receipt selection CLI or restore
is exposed.

Experimental `scripts/retained_state_eligibility.py` inspects the orphan
layout only. It requires the existing non-root linuxhost account/group,
expected home and non-login shell, trusted parent directories, no managed
entry or ownership directory, a private 0700 state directory, exactly the
two 0600 single-link files with matching account ownership, canonical UUID
and lowercase 64-hex control token (newline-terminated, as written by the
agent). It checks read stability and returns only fixed evidence fields,
never values or hashes. Missing/extra/unsafe files, incomplete marker and
ambiguous accounts are refused, not repaired. This is conservative:
legitimate older layouts or leftover agent temporary files (such as
.installation-id.<hex>.tmp or .control-token.<hex>.tmp from interrupted
publication) make the candidate ineligible and require separate expert
review. The inspector neither unlinks these names nor changes link counts. Account layout does not establish account history;
format does not establish v2 provenance. Service quiescence, journal
eligibility, consent, and revalidation under lock at adoption time are
separate gates. The reader is not in the embedded bundle and has no
production caller.

## Historical expectations and environment evidence

The development-only historical_expectations renderer requires an independently
authenticated digest of the exact release payload manifest, an expected
agent version and explicit renderer compatibility identifier v2_fixed_plan_1.
It verifies all fixed payload bytes using the existing bounded staging
reader, copies the frozen bytes into a private disposable directory and
uses the current reviewed planner. It never executes historical source.
Specify the exact allowed system Python command, power choice, interface
pin and Avahi presence. The output is a complete map of expected present
file hashes and explicitly absent paths. Arbitrary retained/customized
drop-ins are not accepted by inference. A caller still needs an independently
trusted manifest digest and reviewed source/renderer compatibility policy;
this module is not an attestation verifier or release catalog. It neither
reads a snapshot to derive expectations nor authorizes a restore. The
candidate reader can use the resulting hashes and version as independent
expectations only when their input provenance was actually established.

The renderer identifier is covered by a frozen synthetic payload and
literal expected per-path SHA-256 values in test_historical_expectations.py.
The contract exercises both an unchanged and a versioned Python command
(including multiple substitutions in a unit), and all eight combinations
of power, interface pinning and Avahi presence. It compares the exact
present-path hashes and absent paths, without computing the expected output
through generate_plan. Changes in rendering semantics must not silently
reuse the old identifier: preserve the old contract or introduce a new
identifier and review historical compatibility explicitly. Do not simply
refresh the golden hashes. Changes to current release source templates
are different: their bytes are bound by the independently authenticated
release manifest; a new release still needs compatibility review, but
does not require a renderer bump if the transformation of frozen historical
inputs is unchanged. This test is not a compatibility guarantee for every
historical template or configuration.

The experimental adoption_candidate context holds the existing shared
installer lock during inspection and while yielding its evidence. It
may create the normal lock file but never writes a journal, stops a
service, repairs permissions or changes credentials. It refuses a journal
directory with anything except the validated lock, even a terminal
record that public status might report as clean, and refuses staged
payload leftovers. Existing journal lock is opened read-only and held
during the journal inspection. The existing explicit systemd absence
query checks all three managed units and the existing enablement scan
checks persistent/runtime dependency directories, including dangling links.
Both journal and service checks run before and after private-state inspection.
Evidence is momentary, not durable consent, a process census, or proof
that arbitrary non-systemd code cannot touch agent-owned files. The
future modifying operation must revalidate under its own transaction
boundary and verify retained identity and key after activation. Real-host
service queries cannot be overridden; fixture roots may inject mocks.

## Proposed versioned wire contracts (experimental)

The experimental codec in `scripts/restore_adopt_contract.py` is the
reviewable candidate for the future privileged boundary. It has **no
production caller, no writer, no dispatch, no embedded bundle integration,
and no new CLI command**. The currently installed helper and Go bootstrap
continue to reject these new versions. Request schemas 1 and 2 and journal
schema 1 remain unchanged; the candidate decoder delegates their existing
validation instead of redefining their grammar.

### Request schema 3

Exact JSON fields, no extras, duplicate names, arbitrary source paths,
commands, credential values or caller-supplied release trust material.
Proposed normalized wire intents (not executable commands):

```json
{"schema_version":3,"action":"restore","snapshot_name":"snapshot-historical","confirmation":"RESTORE"}
```

```json
{"schema_version":3,"action":"adopt","confirmation":"ADOPT","retained_protocol":"v2","power":"disable","wol_interface":null}
```

The restore identifier selects one direct child of the fixed snapshot
namespace. The trusted helper must resolve authenticated historical
expectations independently; neither the request nor its chosen snapshot
supplies that trust. No restore-time overrides of historical power,
Python or interface configuration. Adoption requires an explicit operator
assertion of prior v2 provenance, explicit enable/disable (default disable
in the future CLI), and a nullable validated interface pin. It does not
accept preserve, because an eligible orphan has no installed power
drop-in. The literal confirmations express intent, not authentication or
proof of prior protocol. Both actions still require separate unprivileged
confirmation, explicit administrator authorization, protected entry,
under-lock eligibility and independent evidence checks. Future Go-to-Python
handoff must not accept arbitrary source or Python paths.

### Journal schema 2

Exact common fields: schema (2), transaction_id (32 lowercase hex),
operation (restore/adopt), phase, snapshot_name, before_receipt_sha256,
intent (exact corresponding v3 request), evidence (null or exact
operation-specific object). The original schema-1 journal is not rewritten.
The 2048-byte record and 4096-byte request limits remain.

- Restore intent holds the historical **forward source** name.
  Stage evidence binds source_receipt_sha256, source_manifest_sha256,
  release_manifest_sha256, staged_plan_sha256, agent_version and renderer
  (initially v2_fixed_plan_1). All digests are lowercase SHA-256 hex.
  Actual trust and compatibility must be established by the protected
  caller; a structurally valid digest is not evidence of authenticity.
- Adoption intent includes the retained_protocol assertion and chosen
  settings. Stage evidence binds payload_manifest_sha256,
  staged_plan_sha256, agent_version, retained_layout=verified,
  service_state=verified_absent and pre_begin_journal=verified_empty.
  The last field describes the observation **before** the journal was
  created, not a claim that the newly created journal is absent.
  No private UUID, token, or credential hashes are stored. Eligibility
  evidence and consent cannot prove key equality after activation.
- snapshot_name and before_receipt_sha256 refer **only to the new
  current-before-state** snapshot and its protected receipt, never to
  the selected historical forward source. Recovery must authenticate
  the actual before-state receipt against the journal, verify its
  transaction/operation/name binding and file bytes, and never apply
  the historical source during rollback.

The staged_plan_sha256 field is reserved for the digest of the exact
protected stage manifest bytes, not a digest supplied by the caller.
Before enabling either action, define the bounded canonical stage
manifest/namespace, pinned content, metadata, service observations and
transaction binding; for adoption also bind the verified new payload
manifest and explicitly selected settings. Define how the before-state
receipt writer and recovery reader support the new operations. No current
receipt or staging implementation is altered by this codec. The codec
checks structure and immutable binding, not the underlying files.

| Phase | Evidence | Before-state name and receipt digest |
| --- | --- | --- |
| INSPECTED | null | both null |
| STAGED | required | both null |
| SNAPSHOTTED | required | both required |
| APPLYING / ACTIVATING / VERIFYING | required | both required |
| COMMITTED / ROLLED_BACK | required | both required |
| ABORTED | unchanged from originating pre-apply phase | unchanged, either paired or null |

The transition guard permits the existing sequential phases, pre-apply
ABORTED, and applied-phase ROLLED_BACK only. Operation, transaction ID
and intent are immutable; evidence may be introduced only at STAGED
and the new before-state pair only at SNAPSHOTTED. No terminal record can
transition again. A durable authorization record by itself never allows
mutation: require current eligibility and verified staging before durable
APPLYING. Adoption marker publication is permitted only after APPLYING
and separately reviewed checks; pre-apply abort must not publish it.

### Compatibility and recovery dispatch

The candidate recovery classifier returns a fixed contract identifier
(legacy_v1, restore_v2, adopt_v2) and an action (abort_before_apply,
rollback_before_state, terminal_cleanup). It cannot execute any action.
A terminal v2 record still needs compatible cleanup; it is never proof
of a clean journal. Never resume forward restoration or adoption after
interruption. Schema-1 recovery continues to use the existing rules.
Do not route a new record through the old first-install exception.

Tests exercise the actual current Python journal writer, status,
begin/recovery and terminal cleanup APIs, as well as the exact candidate
wire format. A fresh isolated interpreter uses the actual embedded old
Python modules for refusal tests, not an invented legacy decoder. The
current Go request decoder rejects both exact v3 examples. These are
codec/API compatibility fixtures, not a complete installed old/new
helper matrix or evidence of new recovery support.

Before enabling either operation, implement the trusted stage and
journal reader/writer and separate recovery dispatch; test real old/new
helper combinations including helper promotion interrupted between
renames. In particular, the existing bootstrap normally asks the
current helper for status before promotion, but a missing current and
previous helper can look like a first installation even if protected
journal or staging evidence survives. Close that gap with a protected
absence check (or compatible helper reconciliation) before promotion.
Never retire an unknown helper/artifact or infer a clean state from
unreadable status. Keep existing helper available until its compatible
cleanup completes. No silent fallback to the legacy modifying engine.
Release gate #84 remains separate.

## Experimental durable journal and staged-plan persistence

The fixture-only modules restore_adopt_journal.py and restore_adopt_stage.py
exercise actual persistence under disposable roots. They are not embedded
or called by the production controller. The journal uses the existing
manual installer lock, journal location and exclusive lock; the stage
uses the existing fixed staging base and stage lock. Lock order is manual,
journal, stage. Old helpers see the actual v2 record or staged evidence
and refuse to operate over it. No separate live journal namespace.

The fixture journal accepts a new v3 intent only with no prior journal,
uncertain journal temp or staged payload. It writes canonical sorted
ASCII JSON with newline, 0600 temporary file, fsync, atomic replacement,
directory sync and initial ancestor sync. A recovery context re-syncs
ancestors before returning a handle. Every transition uses the immutable
contract and an explicit trusted fixture verification callback. Such a
callback is not production verification; the actual evidence checks
must be connected by the future controller. The proposed record is
frozen across the callback. Failed publication poisons the forward
handle. Recovery handles permit abort or rollback only, never forward
advancement. Cleanup refuses any surviving stage or unexpected journal
entry; uncertain writes (including a missing journal with a temp file)
are retained for separately reviewed recovery. No automatic deletion
of uncertain files or migration of legacy records.

The new stage format is a complete plan, not the legacy source payload.
Fixed names pending-plan-TRANSACTION and ready-plan-TRANSACTION in the
existing private staging directory, with manifest.json and numbered
N.data files only for present managed entries. The canonical schema-1
stage manifest includes transaction ID, operation, exact intent, sorted
complete managed-path entries (presence, intended mode, length and
SHA-256; absent entries have null metadata) and explicit desired agent
and socket active/enabled flags. Required app/unit files cannot be
absent. Adoption must agree with chosen power and interface presence,
and must activate/enable the agent, with socket state matching power.
The caller still must authenticate the actual staged contents, including
the WOL pin and historical service observations. No stage byte is
executed or applied. The stage digest is over the exact manifest bytes.
Limits: 16 KiB manifest, 2 MiB/item, 8 MiB aggregate. Private 0600 data
files and private stage directory, descriptor-relative bounded reads,
single links, exact expected names, fixed managed paths, checked
metadata and content digests. The reader returns immutable bytes, not
paths for later execution. At INSPECTED it needs the caller's freshly
produced stage digest; at STAGED and later it uses the immutable journal
evidence. Publication writes and syncs before rename, syncs all fixed
ancestors afterwards and poisons the forward handle on uncertainty.

These are persistence primitives, not a usable recovery implementation.
Terminal stage retirement now checks the exact transaction-bound pending,
ready or retiring name and a single flat allowlisted tree. A bound ready
stage must pass manifest and content validation before rename; pending
and unbound ready stages are eligible only for ABORTED with no stage
evidence. A durable retiring name precedes deletion. Retries sync the
namespace before continuing, and validate every surviving entry before
unlinking. Foreign names, unexpected objects and unsafe metadata are
refused. Partial deletion is allowed only under the terminal retirement
contract. Failed retirement poisons the handle after rename/deletion
begins. Even an empty existing staging base requires explicit retirement
and sync in the current context before journal clearing.

The separate fixture reconcile_complete_temp operation accepts exactly
one complete canonical v2 temporary record. With a durable v2 record
it must be a valid next transition; without a record it must be an
initial INSPECTED write and no staged payload may exist. An explicit
trusted fixture verifier must establish the applicable real-world
unchanged/restored state before evidence may be discarded. The temp is
never promoted; current record and ancestors are synced first. The separate
fixture reconcile_partial_temp operation now supports a strict byte prefix
(including zero bytes) of a valid canonical next schema-2 transition
when the durable schema-2 record exists. The trusted verifier must
independently reconstruct the proposed full record (including any new
stage or snapshot evidence) and establish the applicable unchanged or
restored state under the same locks. The partial bytes are not a source
of truth; prefix equality does not identify a writer, authenticate
evidence, or authorize a phase. The safety basis is the write-ahead rule:
no work belonging to a phase starts until that phase's journal record is
durable. Therefore, beside an already durable schema-2 record, discarding
a leftover temporary write cannot discard authority for work that began:
an unfinished forward transition describes work that did not start, while
an unfinished ROLLED_BACK publication leaves the prior applied phase
durable and recovery can safely repeat the rollback. Prefix matching is
defence in depth and useful diagnostic evidence, not what makes discard
safe. In particular, an empty temporary file is a prefix of every
candidate and binds nothing. A complete candidate goes through the
complete-record path. Both methods share the same ownership, exact entry,
transition, callback, byte/metadata recheck and durability guards.
Neither method promotes the candidate. A partial orphan with no durable
record, conflicting or multiple records, unsafe metadata, unknown schema
or nonmatching prefix is preserved. In particular an empty initial write
cannot identify its originating schema or operation. Expert intervention
may still be required for those cases. No guessing based on filenames.

If a discarded temporary record proposed VERIFYING -> COMMITTED, the
durable VERIFYING phase still controls recovery: roll back even if all
forward changes and checks had actually succeeded. A fully applied plan
is not a durably committed transaction. This is expected behavior, not
a recovery regression.

A corrupt bound ready stage cannot be retired by the normal path even
after a terminal record. Before live use provide a separately reviewed
explicit administrator quarantine path (not force-delete or automatic
digest bypass): independently verify the terminal managed/service and
credential outcome, exact transaction identity and safe stage layout,
then durably move the stage into a fixed protected non-executable
quarantine namespace outside the active staging scan. Require a
transaction-bound quarantine receipt, no replacement, checked same
filesystem publication and synchronization of both parents, and a
retry-safe check before journal clearing. Preserve bytes and refuse
unsafe or foreign objects; neither quarantined stage nor its receipt
can authorize forward work. Until implemented and accepted, preserve
the stage and journal for expert review. Do not offer a live manual
deletion recipe. A retiring stage has already crossed the verified
retirement boundary; partial deletion precludes checking the original
whole-tree digest, so retries inspect surviving entries only.

## Experimental schema-2 current-before-state receipts

restore_adopt_before.py captures the actual fixed managed paths in
a disposable fixture root after STAGED, while the existing manual and
journal locks are held. It rechecks the journal-bound staged plan first.
Read only the eight approved managed paths through no-follow directory
descriptors; only ENOENT means absence. Present files must be regular,
single-link, exact installed mode, expected owner/group and bounded size.
The initial policy accepts complete, structurally v2 installed state
for restore (or all managed files absent with all service flags false),
and only all-absent managed files for adoption. No partial, damaged,
legacy or unsafe layout. Unlike install/upgrade/repair's existing
capture policy, restore deliberately refuses damaged installed modes
rather than preserving them for rollback. An otherwise safe managed
regular file with an unexpected mode produces the fixed
current_state_permissions_damaged diagnostic. For a recognized v2
installation, the future user-facing diagnostic should instruct the
operator to finish abort/recovery and clear the pending transaction,
then use the supported repair operation before retrying restore.
Do not advise repair for unknown protocol, unsafe objects, ownership
mismatches or ambiguous state; do not repair permissions implicitly
during restore. The existing v1 repair capture semantics are unchanged.

Restore onto a genuinely clean host is an intended supported case,
conditional on independently verified clean layout and service state.
An empty managed-file capture with false service flags alone is not
that proof. Unmarked retained private state requires the explicit
adoption path; restore must not implicitly adopt it. The eventual
controller must separately establish account, owner marker, retained
state, and service/enablement eligibility, and define safe activation
and recovery for the clean case before exposing it. These file/boolean
checks alone are not proof of protocol provenance, clean systemd
state or orphan eligibility.

The new rollback format deliberately differs from schema-1 historical
source snapshots: snapshot-v2-TRANSACTION is a fixed, exclusive directory
under the protected backup base. Manifest schema 2 records transaction,
operation, exact intent, complete sorted managed file metadata, SHA-256
and explicit null absence, and four observed service booleans. File
copies have private mode 0600; original intended metadata is in the
manifest. receipt.json (schema_version 2) binds the transaction,
operation, capture phase STAGED, distinct new snapshot name, manifest
digest and staged-plan digest; release_authenticity is not_verified.
No UUID, key, credential hash, owner marker or account data is captured.
This is a current-before-state receipt, not publisher or historical
release provenance. Legacy snapshot validators refuse schema 2.

The receipt is written last, after the complete manifest and file
copies. Sync all files, directory and fixed ancestors, re-read and
validate receipt and pinned file bytes, then compare with fresh current
file and service observations. Publication uncertainty poisons the
handle, and an incomplete or already existing deterministic snapshot
is preserved rather than overwritten. Only a later verified
SNAPSHOTTED transition binds its digest in the durable journal.
Unbound partial snapshots are forensic evidence, not eligible recovery
sources; their eventual cleanup requires a separate reviewed policy.
A failed publication that leaves the deterministic snapshot directory
prevents recapture in that transaction. It must take the verified
pre-apply abort path; do not retry capture with a different name.
Stage retirement and terminal journal clearing do not prove that an
unbound before-state directory is absent, and do not delete it. Preserve
such directories independently of stage retirement. A future operator
reconciliation/quarantine policy must distinguish unbound forensic
snapshots from bound rollback evidence and must not retire a referenced
rollback source.
The fixture inspect_unbound_before operation now classifies the exact
transaction-derived directory only while holding an ABORTED journal
with no bound snapshot name or receipt digest. It refuses a historical
source collision, and an existing directory without stage evidence.
The guarded no-follow walk checks a flat allowlist, ownership, private
mode, single links, bounded sizes and stable directory identity. It
reports absence or preserved unbound layout with manifest/receipt
presence and original-file count only. Empty/truncated files are
permitted as forensic evidence; no content is parsed, authenticated,
rebound, renamed or deleted. A complete-looking tree remains unbound.
This read-only classification is independent of operator quarantine. It does not authorize abort or journal clearing
or prove that the managed state is unchanged.
A read at STAGED uses the freshly produced capture reference; later
reads use the journal's immutable name and receipt digest, never a
caller override. The reader checks exact binding, canonical manifests,
complete metadata, hashes, names and limits and returns pinned bytes.
The restore source is never used as the current-before-state snapshot.

restore_adopt_verify.py now supplies concrete fixture verification
for bind_stage (independent expected rendered plan, not hashes derived
from the stage) and bind_before (bound receipt and actual current
managed bytes/metadata and service observation). check_apply_evidence
rechecks the staged plan and receipt against independent expectations
and fresh current state; it does not advance to APPLYING.
The eventual SNAPSHOTTED -> APPLYING verifier must invoke this check
inside the same active handle and lock scope, together with the other
operation-specific eligibility and continuity checks. An earlier
successful read-only call is never permission to mutate; the controller
must use the pinned evidence from that transition and require durable
APPLYING publication before any managed change.
check_rollback_evidence compares actual current fixture files and
observed service flags against the journal-bound before-state; it does
not mark ROLLED_BACK. The generic low-level fixture transition API
remains for persistence tests. A future controller must also verify
actual systemd observations and enablement absence, account/owner
marker policy, retained UUID/key equality without logging private
values, authenticated source and current eligibility/consent. These
checks must be bound to the relevant transitions rather than treating
a fixture observer or structural record as proof. Neither module
invokes systemd, applies files, changes credentials or permits live
roots. No production or embedded bundle changes.

The separate fixture restore_adopt_quarantine.py implements explicit
unbound-before quarantine only. It requires the exact ABORTED unbound
journal with stage evidence, literal QUARANTINE confirmation and a
trusted independent terminal-outcome verifier on every attempt. It never
reads credentials or applies a plan. A fixed private quarantine-v2 child
of the backup base holds unbound-TRANSACTION and its separate JSON receipt,
outside historical snapshot naming. The receipt binds the exact canonical
terminal journal digest, operation, transaction, source/destination names,
and opaque file names, lengths and digests (including empty partial
files). It is not provenance, rollback authority or proof of outcome.
No-follow private bounded reads and exact flat allowlist, content recheck
after verification, same-filesystem Linux renameat2(RENAME_NOREPLACE)
with no fallback, and receipt/file/ancestor sync precede the move.
Both parents and the retained bytes are checked and synced after it.
Retry recognizes either source plus matching receipt or destination plus
matching receipt; it refuses both/neither, unsafe entries, receipt
mismatch, destination without receipt and incomplete receipt publication.
An incomplete receipt is retained for separately reviewed reconciliation,
not overwritten. The handle is poisoned on publication uncertainty.
This is an optional explicit fixture operation, not a requirement or
authorization for clearing a terminal journal; existing preservation
without quarantine remains possible. No production/embedded changes.

Portability limitation: the fixture resolves the libc renameat2 symbol
through ctypes.CDLL(None); glibc 2.28 and later provide this wrapper.
On libc builds without that symbol (including musl/Alpine builds lacking
the wrapper), quarantine fails closed with quarantine_noreplace_unavailable.
Kernel and filesystem support for RENAME_NOREPLACE is independently
required; an unsupported flag (for example EINVAL) or other rename error
fails closed with quarantine_publication_failed. The original snapshot
and any published receipt remain evidence for retry or expert review.
There is no plain rename fallback or architecture-specific syscall
fallback. These are known capability limitations, not permission to
weaken the no-replacement guarantee. Before live integration, provide
a supported operator reconciliation path for unavailable quarantine
and partial receipts; never recommend deleting evidence to unblock it.
See Linux rename(2): https://man7.org/linux/man-pages/man2/rename.2.html.

Remaining: actual phase-specific execution and recovery verification,
partial orphan/ambiguous-write policy, incomplete quarantine receipt
reconciliation, corrupted-stage quarantine implementation, and compatible
helper provisioning. Never claim a valid
record or stage alone proves authorization or restored state.
The existing v1 writer, recovery, Go bootstrap and bundle remain unchanged.

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
