# Protected credential continuity for the stable Linux installer

**Proposed design for review, not an implementation or release authorization.**
Baseline: main `e1ad10f` after #154 and #156. Tracks #155, I11 and I7
in the [architecture audit](LINUX-INSTALLER-ARCHITECTURE.md).
Related: #152, #98, #101, #84, #150. This concerns the existing
install/upgrade/repair/uninstall/recover operation set (schema-1 engine).
No restore/adopt, WOL mutation, account adoption, credential migration,
or new public install operation is part of this design.

## 1. Goal and non-goals

Before a terminal outcome asserts preservation, independently establish
that each pre-existing installation-id and control-token remains the
same protected filesystem object with unchanged relevant metadata.
This applies to stopped agents and uninstall as well as active runtime
verification and rollback after process interruption. Existing state is
never regenerated, copied, restored, deleted, or corrected to make a
comparison succeed. Explicitly distinguish originally absent credentials
from retained credentials. Continue to require the existing file,
service, ownership and runtime checks: continuity is an additional gate,
not a replacement for those checks.

The current agent's persistent_value creates missing files by exclusive
temp creation and hard-link publication; it never replaces an existing
credential. The protected installer managed-file allowlist excludes both.
The four reproduced fault-injection cases in #155 demonstrate missing
detection, not a spontaneous credential rewrite in normal operation.

Threat model: authenticated installer, trusted root, cooperating
installer writers, normally behaving agent and kernel/filesystem.
File identity and change metadata are evidence in that model, not a
cryptographic proof of unchanged contents. Cloned/restored filesystems,
inode reuse, coarse or unreliable timestamps, hostile root/kernel,
offline modifications and some filesystem recovery behavior can defeat
or invalidate the inference. No credential value or credential hash in
the new evidence, journal, logs, CLI or diagnostics. No new reads of
credential contents for continuity; the pre-existing private UUID
runtime comparison remains separate and is not serialized. No claim that
metadata verifies token format, possession or protocol authentication.

## 2. Observations and eligibility

Use fixed local paths under /var/lib/linux-host-agent for the systemd
agent, never a client-supplied path or the interactive user's state.
Acquire the existing shared manual installer lock, then journal lock,
with the existing stage lock when needed. All observations are made by
trusted code within that ownership context. No stop, chmod, chown or
other managed mutation before durable APPLYING. A live agent is not
serialized by those locks: read twice and rewalk fixed paths around each
observation; if first-start publication is in progress or identity
changes, refuse/retry instead of claiming an atomic pair observation.

Descriptor-relative no-follow traversal, bounded exact names, validated
root-controlled ancestors and the agent-owned private StateDirectory.
Resolve and verify the linuxhost account/group and expected permissions,
including the directory ownership. Refuse unsafe/nonregular/linked
objects, unexpected mounts or access failures rather than treating them
as missing. Only ENOENT at an otherwise verified fixed path establishes
absence. No account or directory creation as part of inspection.
Distinguish missing directory on a clean host, missing credential in
a safe existing state directory, and an inaccessible or unsafe path.
No-follow directory descriptors and held file descriptors must match
visible entries after capture and before comparison; exclude atime.

For each existing file, record a private observation of filesystem
type, filesystem UUID, Btrfs subvolume ID where applicable, inode, size,
file type/mode, uid/gid, link count, mtime_ns and ctime_ns. Record safe
state-directory identity/ownership when present (not directory mtime or
ctime as a continuity equality test, because creating a missing
credential legitimately changes those). State-directory absence and
account absence are explicit states. Do not use st_dev/f_fsid as a
persistent identity. Within one observation, volatile stat/mount data
may detect a race; it is not evidence across boot. Recheck account
mapping and path identity. Strict canonical bounded encoding, explicit
types/ranges, reject duplicates and unknown fields; no generic arbitrary
paths or caller-provided fields.

The normal files are private mode 0600 with canonical UUID/token sizes.
Existing read_saved_identity permits some legacy UUID lengths/modes;
inventory and validate the accepted historical layouts before choosing
a stricter predicate. Do not silently break supported upgrades or
read/repair credentials to fit a preferred format. A different mode or
size may be a refusal condition but cannot establish content validity.

### First-start publication and hard links

A crash between link and unlink can leave exactly the published file and
its own .installation-id.<hex>.tmp or .control-token.<hex>.tmp alias.
The existing UUID reader deliberately allows a two-link case. Never
treat arbitrary nlink=2 as safe. Verify the exact name pattern produced
by persistent_value, expected owner/mode, matching inode/metadata and
complete accounted link count using held descriptors. Unknown aliases,
external links, symlinks and unstable observations refuse. Preserve
leftover temp evidence; do not delete it just to obtain a convenient
single link. A link disappearing after capture changes ctime/link count:
it is not a continuity pass even if contents probably remain the same.
Acceptance must cover normal first-start completion and legitimate
interrupted publication; the conservative initial behavior may require
retry/expert review for unstable or ambiguous state.

## 3. Persistent filesystem identity is a release feasibility gate

The existing development-only wol_fs_identity.identify(fd) (#98) is a
candidate building block, not a supported installer dependency today.
It uses descriptor mount identity and FS UUID queries for ext4/XFS and
native Btrfs FSID/metadata UUID plus subvolume ID; refuses unsupported
ABIs, filesystems, ioctl or ambiguous UUIDs. Review and promote only the
necessary read-only implementation, including bundle dependencies.

The local overlayfs probe on this baseline returns None. That is
expected for the prototype, not proof of ext4/XFS/Btrfs behavior.
Fixture observers may inject deterministic identities only on
disposable roots; no override of live identity observations. Test
supported kernel/filesystem combinations, including the older supported
Debian/Ubuntu systems and Gentoo Btrfs, separate state mounts, read-only
mounts, and actual reboot. Include the case of systemd StateDirectory
ownership/mode management: a legitimate chmod/chown or metadata
transition must not be confused with a verified unchanged observation.
Do not weaken comparisons silently to pass such a test.

Before adopting this as an unconditional stable gate, determine whether
the stable-identity implementation is available on the intended Linux
support matrix. If it is unavailable, choose an explicit reviewed
support/diagnostic policy or a different reliable persistent observation
mechanism. No silently weaker cross-reboot comparison, no st_dev or
f_fsid fallback, and no reporting not_verified as verified. A boot-scoped
observation may be useful for diagnostics, but does not satisfy I11
after reboot. An unsupported pre-existing credential filesystem must
refuse before APPLYING under the strict contract; that can affect normal
upgrades/uninstall, so verify feasibility before production integration.
Clean installs with absent credentials must also establish safe later
observations and support for the resulting state, or refuse before
mutation. Do not infer support from the filesystem containing /tmp.

## 4. Durable evidence and old-helper compatibility

### Storage alternatives

| Option | Assessment |
| --- | --- |
| Add fields to #116 provenance receipt | Existing historical reader checks exact keys and schema. Requires versioned reader migration; old reader refuses. |
| Add files inside legacy snapshot | Historical eligibility requires an exact snapshot entry set; avoid changing the snapshot format. |
| Separate protected sibling sidecar only | Keeps old manifest and provenance formats intact, but old recovery ignores it and new recovery cannot tell required-but-missing evidence from a historical transaction. Insufficient by itself. |
| Sidecar plus explicit new journal binding before mutation | Recommended for review. Old strict journal reader refuses the enhanced record; new reader knows evidence is mandatory. Keeps operation set and rollback/provenance formats unchanged. |

The current journal reader accepts exactly the schema-1 fields, and
rejects either an extra continuity field or an unknown schema (local
validation probe confirmed). The older controller's _restore_snapshot
does not read the #116 provenance sidecar; a new standalone sidecar is
also invisible to it. A staging compatibility fence alone can prevent
legacy cleanup but does not by itself prevent legacy rollback mutation
or writing a terminal record while a valid schema-1 APPLYING record
exists. The normal Go bootstrap retains the recovery-compatible helper,
but deletion/replacement or explicit downgrade must not circumvent
the evidence contract. No reliance solely on version strings.

### Proposed narrow journal evolution

Retain existing schema-1 initial INSPECTED and STAGED publications,
including their initial-write recovery rules. No managed mutation
occurs in either phase. After observing credentials and creating/syncing
the existing rollback snapshot and #116 receipt, publish a separate
private sibling continuity receipt in the protected backup base, with
a fixed derived name (e.g. .<snapshot>.continuity-v1.json) outside
snapshot selection. Bind schema/version, transaction ID, operation,
snapshot name, manifest digest, and two fixed-name observations plus
state-directory/account observations. No credential-derived hash:
a digest over the canonical metadata receipt is permitted and binds
only non-content metadata. Do not place even this metadata in public
output. Private root-owned 0600 single-link bounded file, no-follow
safe ancestry, exclusive publication, readback and sync file and
ancestors. Never overwrite a partial or conflicting receipt. Recheck
source observations after publication and before authorizing APPLYING.

At the transition from STAGED to SNAPSHOTTED, publish an explicitly
versioned protected record binding the exact snapshot and continuity
receipt digest. Proposed distinct journal schema identifier (e.g. 3,
subject to review; 2 is reserved for fixture restore/adopt). This is
a narrowly enhanced envelope for the existing schema-1 operation set,
not enabling schema-2 features. Carry the immutable binding through
APPLYING, ACTIVATING, VERIFYING, COMMITTED, ROLLED_BACK and bound ABORTED.
Do not allow a transition back to the old envelope, a different digest
or a different snapshot. Existing schema-1 journal readers must refuse
the durable enhanced record rather than falling back to legacy
recovery, including the manual installer status guard and old
bootstrap promotion path. The exact wire/schema decision requires
independent review; an explicitly versioned extension with equivalent
old-reader refusal is an alternative. Do not silently change the schema
1 exact-key contract.

This ordering is intentional: an interrupted enhancement publication
with durable STAGED still authorizes no managed mutation, and the
ordinary old pre-apply abort may preserve the unbound sidecar/snapshot.
The enhanced record must be durable before APPLYING can start.
No new-schema orphan initial temp is introduced by this proposal;
#148 remains a separate requirement for schema-2 initial publication.
An interrupted write with a durable enhanced predecessor must be
handled by the enhanced recovery path only; never infer forward
authority from a temporary record. Test actual historical builds,
not only the current strict decoder.

For old schema-1 records already in progress, retain compatible
recovery under their original contract. They cannot retroactively
acquire before-state continuity evidence; disclose that limitation.
A missing or malformed mandatory receipt for an enhanced record is
recovery_required, not the legacy-compatible case. New transactions
must never skip enhancement before APPLYING. No option to downgrade
a pending enhanced transaction or bypass its checks. #150's missing
helper presence check and independently authenticated recovery-helper
availability (#84) are relevant to this boundary; test both present and
missing helper scenarios before deploying the enhanced envelope.

## 5. Controller integration and terminal outcomes

| Phase / observation | Required behavior |
| --- | --- |
| INSPECTED/STAGED, no bound observation | No managed mutation; old-format pre-apply abort may preserve unbound evidence; do not assert continuity. |
| SNAPSHOTTED enhanced record | Valid receipt, unchanged retained baseline before APPLYING; abort must independently verify if evidence is bound. |
| APPLYING/ACTIVATING/VERIFYING | Recover by rollback, never resume forward work; validate binding and evidence before recovery mutation. |
| Forward verification | Existing file/service/runtime checks plus independent credential continuity; active runtime UUID check remains distinct. |
| Rollback verification | Existing managed/service restoration checks plus the same retained continuity check before ROLLED_BACK. |
| COMMITTED (including uninstall) | Never roll back solely to clean a valid committed record. Reverify continuity before terminal evidence retirement/clear; on uncertainty preserve and diagnose. |
| ROLLED_BACK or bound ABORTED | Reverify before cleanup, do not discard required evidence on a mismatch. |
| Receipt missing, corrupt, ambiguous or wrong transaction | Refuse mutation that would depend on that evidence; preserve journal, snapshot and receipt. |

A failed forward continuity check must not produce a false success or
be converted into a successful rollback merely because managed files
were restored. If the bound receipt is valid but the credential
comparison fails, distinguish that from missing/unsafe evidence:
the existing authorized managed-file/service rollback may still be
necessary to avoid leaving a failed installation. It must not modify
credentials to restore a metadata match. If continuity remains
unverified after rollback, keep the durable nonterminal record and
protected evidence, return a redacted recovery_required result.
Design an explicit expert/operator resolution policy separately; no
automatic reset or forced deletion. If receipt integrity is unknown,
do not infer rollback authority from it. Review whether the original
journal-bound managed snapshot can be used for a safe restricted
rollback in that case; no such fallback is authorized here.

For a retained credential, disappearance, replacement, content rewrite
detected through metadata, owner or mode change, unexplained link
change or stable filesystem identity mismatch are failures. For an
originally absent credential, no claim of preservation: it may remain
absent for stopped/uninstalled states or be newly created by the agent
during authorized activation/recovery. Verify safe newly present
objects and preserve them; active agent/runtime validation remains
required when appropriate. An entirely absent baseline is not a waiver
of path safety. Define first-start observation binding before claiming
a newly created object remains unchanged during later cleanup;
do not require absence after rollback if first start legitimately
created state. Never change the documented retention policy for
account/owner marker/private state. Exact first-install behavior,
including partial first-start generation, needs separate tests.

Recheck continuity after all state-changing operations and immediately
before terminal publication. Centralize the checks so exception paths,
explicit recovery, finish_terminal_cleanup and opportunistic
terminal cleanup cannot bypass them. The enhanced status path must
report terminal cleanup pending until evidence retirement and journal
clear are complete, including payload-free uninstall; begin must not
silently reap an enhanced terminal record. Keep the receipt with its
snapshot after journal clearing, as protected forensic metadata.
Do not delete the evidence to make status clean; retention/expiry is
separate. Do not claim protection against a hostile privileged writer
between final verification and publication.

Public identity_preserved currently describes the UUID/runtime check,
not the pair of credentials. Preserve its meaning until an explicit
wire/UI contract review; use a fixed redacted failure classification
for continuity failures and separately distinguish no prior identity.
No filesystem UUID, inode, timestamps, credential values, hashes,
raw exceptions or sidecar data in result/status/diagnostics.

## 6. Implementation sequence and acceptance

Do not implement the entire controller or change the embedded bundle
in the design PR.

1. Agree on the threat model, supported filesystem matrix and receipt/
   journal compatibility design. Implement and test the metadata
   observer in fixtures, including anchored link evidence, unsafe
   ancestors, owner/mode, descriptor/name replacement, same-size
   rewrite, absence, unsupported filesystem, and zero secret reads.
   Exercise existing filesystem identity primitive on supported
   physical filesystems before mandatory production use.
2. Design strict metadata receipt codec and durable exclusive
   publication/readback; test short writes, sync failure, conflicting
   evidence, directory replacement and binding errors. Preserve
   original snapshot/provenance compatibility; test old eligibility
   reader with a sibling receipt. No mutation authority yet.
3. Implement the narrow enhanced journal transition and recovery
   dispatcher. Fault-inject every binding/publication boundary;
   freeze old journal-reader tests and test archived helpers,
   status, manual entry points, bootstrap, missing evidence and
   missing helper. Prove old recovery cannot mutate/clear enhanced
   evidence and new recovery can handle original schema-1 records.
4. Integrate observer and checks in install/upgrade/repair/uninstall,
   all rollback paths and terminal cleanup. Use the actual controller
   with simulated service operations and redo all four #155 probes;
   prove no false successful terminal outcome. Include interrupted
   COMMITTED temp vs durable COMMITTED, inactive agent, newly generated
   credentials, service failures and cleanup-only retries. Preserve
   journal/snapshot on uncertainty and the existing identity result
   semantics unless deliberately revised.
5. Review actual release-supported systemd/filesystem behavior,
   independently authenticated helpers and safe migration/downgrade.
   Run complete Python/Go/embedded bundle/CI tests, independent
   review, physical non-destructive metadata observation before and
   after normal reboot, and supervised acceptance on reversible
   hosts. No deliberate fault injection on hydra's working install.

#155 remains open. #101/#84 and existing release gates remain open.
Nothing in this design authorizes schema-2 production deployment,
changes to released rc.2 assets or live-host testing.
