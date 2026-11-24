# Protected persistent Wake-on-LAN — transaction design and release gates

Related: #88, #93, #94. This document is a design contract for a later
implementation, not a claim that writable WOL is supported today.

## Why the next increment hardens service-state verification

A journal is only as reliable as its before-state capture and rollback
postconditions. The original installer used boolean is-active/is-enabled
exit-code checks. A timeout, inaccessible bus or absent unit could look
like an intentionally stopped/disabled unit. The physical uninstall path
already uses explicit LoadState, ActiveState and UnitFileState evidence.

The wizard's installer transaction now applies those explicit observations
to install/upgrade/uninstall snapshot capture, successful installation and
rollback verification. Existing agent/socket units must have loaded
persistent enabled/disabled states. A definite failed state or
activating/auto-restart (including auto-restart-queued) is recorded as
inactive for rollback, retaining
enablement, with an optional retry flag for successful repair/upgrade.
After APPLYING, stop and clear failure/start-limit state before retrying
the broken service. Intentionally stopped healthy agents are not started.
Other transitional, masked, runtime-only, partially missing or unknown
states abort before application. A fresh install requires explicit absence
of all three units and no managed dependency entries.

Fresh-install rollback disables/stops and resets failed units while their
files are still present, then verifies quiescence and absence of managed
dependency links before removing files. After restoration and daemon reload,
clear failure counters and verify explicit absence of all three units and
no dangling managed entries in persistent/runtime dependency directories.
Uninstall similarly resets failed units and checks dependency entries.
Existing-install rollback restores normalized activity and original enablement,
not a synthetic failed state. Failed reset/stop/disable commands do not
count as success: the explicit final observations decide. A stopped agent
skips HTTP health verification, not service verification.

This retains the existing snapshot schema, with optional retry metadata
used only for forward activation. Manual installer semantics, root protocol,
WOL policy and network settings are unchanged. An unusual legacy snapshot
or unresolved administrator-created dependency link may need manual
recovery; do not delete an ambiguous link to claim success.

### Diagnosing a fresh-install state refusal

A pre-apply existing_state failure can indicate a systemd query failure,
nonrepresentable service state, or leftover managed dependency entries.
The existing public protocol does not distinguish these yet. Inspect
LoadState, ActiveState, SubState and UnitFileState for the agent, power
socket and helper. For dependency entries, the following read-only
commands report matching names and symlinked dependency directories
without traversing links:

```sh
for dir in /etc/systemd/system /run/systemd/system; do
    [ -d "$dir" ] || continue
    find -P "$dir" -mindepth 2 -maxdepth 2 \
        \( -name linux-host-agent.service -o \
           -name linux-host-agent-power.service -o \
           -name linux-host-agent-power.socket \) -print
    find -P "$dir" -mindepth 1 -maxdepth 1 -type l \
        \( -name '*.wants' -o -name '*.requires' -o \
           -name '*.upholds' \) -print
done
```

A symlinked dependency directory, even if administrator-created and
legitimate, is deliberately not traversed by the protected verifier.
Unreadable trees and unresolved managed entries prevent fresh install or
rollback from claiming a clean state. Investigate ownership and intent
before any manual cleanup; do not delete links just to pass the check.
A dedicated redacted diagnostic in the inspector or wizard is follow-up
work; no public error protocol change is required for this increment.
Validate fresh-install absence and stable installed states on real systemd
versions before general release. No deliberate physical fault injection on
a working host is needed.

## WOL is an independent optional operation

A user can install Computer Host LAN solely for monitoring and decline
network configuration. Power-helper enablement, interface pinning,
persistent network policy, and immediate runtime flags are separate
decisions. Preserve all existing policy by default. A failed optional WOL
operation must not roll back an already committed agent install.

The accepted planner's fixed-enum output is advisory. Its redacted JSON
must never be accepted as an authorization, a target path, a profile
identifier, or an executable mutation plan. In particular, the observed
base declaration and inventory are not an atomic snapshot.

### First writable scope

Start with a systemd device-specific local rule that contains exactly one
literal PermanentMACAddress match, has unspecified WOL, has no earlier
potential match or relevant drop-ins, and has verified permanent identity,
hardware capability and supported systemd behavior. Do not introduce a
new competing .link file. Do not modify the base file or a shared/default
rule. A current-MAC-only rule such as the accepted Gentoo configuration
is preserve-only. Unknown directory layouts or policy syntax are refused.

A potential scoped drop-in is a candidate only if the actual supported
systemd implementation applies it as intended. Confirm with official
documentation and fixture/VM behavior without using a live mutating
udev test builtin on the user's host. Do not offer a write until the
scope and supported syntax are verified.

Initially make persistent-policy changes only. Do not set runtime WOL
in the first writable implementation; this removes a second external
effect from the transaction. Explain that a reboot/link reinitialization
and actual magic-packet test are still necessary. No forced reboot,
link bounce, networking restart, IP, route or firewall changes.

NetworkManager is a separate later backend. Real wired NM acceptance is
required before a write path: exact old and proposed flags, persistent
profile identity and NIC binding, no SecureOn/credentials, no shared
profile, explicit user consent (especially explicit none), and verified
rollback. Never silently replace DEFAULT/IGNORE or erase other flags.

## Journal and recovery compatibility

Before adding a new operation, review the installed helper's protected
manifest, schema, bootstrap promotion, manual installer lock and
recovery dispatcher together. One installer-wide exclusion domain must
cover agent transactions and WOL transactions. Reuse the existing
protected journal/lock architecture where possible, but do not put
arbitrary network targets into core.MANAGED_PATHS or the agent snapshot
restore allowlist. WOL before-state records require a distinct validated
format and a dedicated recovery dispatcher. Old helpers must fail
closed on an unknown operation, never reinterpret WOL as an agent
transaction or clean up its snapshot. A regression test pins the current
journal reader's refusal of an unknown configure_wol record, including
status, begin and resume_recovery. When adding the new format, retain a
frozen old-reader compatibility fixture and test both upgrade/downgrade
and interruption boundaries before wiring a new root request.

A prospective operation follows:

1. Obtain separate explicit approval after preview, no automatic action
   during installation. Bind approval to a protected revalidated plan;
   if the reviewed target or before-state changes, require renewed consent.
2. Acquire the shared lock, reject pending recovery and independently
   inspect current policy, NIC identity, support and exact target scope.
3. Record INSPECTED/STAGED with no network effects. Snapshot the intended
   target's absence and protected parent identities, exact base rule
   identity/content and relevant policy evidence. Bind the snapshot to
   the transaction ID, write and fsync private record and directories.
4. Record durable SNAPSHOTTED/APPLYING before creating any owned
   directory/file. Derive a fixed reserved drop-in basename only from
   the checked base rule; do not trust a client-supplied path or command.
   No-follow directory traversal and no-clobber publication are required.
   Preserve unrelated parent contents and administrator changes.
5. Verify exact intended bytes, ownership, mode, file identity, scope
   and continued precedence/identity. Record persistence pending reboot,
   not persistence verified. Commit durably before retiring journal.
6. If interrupted before APPLYING, abort only with evidence that no
   network effect occurred. If interrupted after APPLYING, recover by
   verifying ownership and the recorded intended effect, then undo only
   the transaction's own creation and verify restoration. Never resume
   unapproved forward mutation automatically.

## Ownership and failure boundaries

A preexisting destination, even byte-identical, is not owned by this
transaction. No-clobber publication and a protected receipt must
distinguish ours from an administrator's concurrent creation. The
publication/receipt crash window must be explicitly addressed; identical
contents alone are insufficient proof of ownership. Consider a durable
staged inode and an atomic hard-link publication (same filesystem), with
the protected receipt recorded before publication and an inode comparison
during rollback. Test cross-filesystem and Btrfs behavior; refuse if
the required identity/durability guarantee cannot be obtained. Do not
remove another writer's file, directory or policy. If an applied file is
replaced/edited or provenance cannot be established, retain recovery
state and report recovery required rather than force restoration.
Rollback must not remove nonempty parent directories or unrelated
configuration. A newly created parent must be proven owned before any
cleanup; alternatively require a preexisting protected directory in
the first implementation.

The existing agent uninstall retains network policy. Even an
installer-owned persistent rule should not be removed by a normal
uninstall. Any explicit WOL cleanup action must use the same ownership
and conflict guarantees.

## Publication primitive (development-only increment)

`scripts/wol_publication.py` implements a small filesystem-only component.
It has no CLI, no root request, no installer caller and no bundled copy.
The tests open only disposable fixture directories. It is not a complete
WOL transaction or permission to modify a real host.

The future trusted controller supplies two already-open, independently
validated directory descriptors: an existing protected device-specific
drop-in directory and a separate private receipt directory. Both are
checked for ownership and permissions. Directory identities are bound
to the receipt. There is no arbitrary target name, content or directory
creation/removal in the primitive. Its fixed target and exact bytes are:

```ini
# 90-computer-host-wol.conf (filename, not part of the contents)
[Link]
WakeOnLan=magic
```

Only the two INI lines (and trailing newline) are written.

1. After the future controller records durable APPLYING and confirms the
   approved policy, prepare creates a hidden transaction-specific anchor
   using O_EXCL in the same directory as the destination. It is not a
   .conf file and is not intended to be parsed by systemd. The inode is
   written, set to mode 0644 and fsynced, then the directory is fsynced.
2. Create the transaction-specific private mode-0600 receipt using
   O_EXCL, fsync its contents and directory. The schema binds the
   transaction ID, absent target before-state, both directory identities,
   anchor identity, group and modification timestamp. Schema 2 stores
   (f_fsid, st_ino) for each directory and the anchor, never the
   mount-local st_dev. The anchor must be on the same current device
   as its policy directory. Current-mount comparisons still use
   (st_dev, st_ino) when comparing the anchor with the target.
   Receipt parsing rejects duplicate/unknown fields, older schemas,
   invalid values, unexpected links, permissions, missing data and
   oversized records. Missing or zero filesystem IDs refuse staging.
   Public operations translate filesystem errors to fixed PublicationError
   messages with suppressed exception context; an occupied foreign target
   is a distinct PublicationConflict, including EEXIST at atomic link().
3. Only after prepare has returned successfully may the authorized
   live controller publish: hard-link the anchor to the fixed target.
   The atomic link operation cannot replace an existing target, even
   one created concurrently with identical contents. Verify the inode,
   contents, mode, owner, group, timestamp and expected link count,
   fsync the anchored inode and directory, and verify again.
4. For rollback, retain the anchor and receipt. If the target is absent
   and the original anchor remains intact with one link, the effect
   is unpublished. If the target and anchor are the same verified inode
   with exactly two links and the original contents/metadata, remove
   only the target, fsync and reverify. Any mismatch fails closed.
   Rollback is idempotent while the evidence remains. A replaced file
   with identical contents is not accepted as owned.
5. No receipt/anchor retirement is implemented here. A committed live
   publication retains its hidden anchor and private ownership record
   until a separately authorized, verified WOL removal. The active
   transaction journal may be retired after commit, but not the ownership
   evidence needed for later removal. Normal agent uninstall preserves
   both links and the private ownership record. Future status/uninstall
   documentation must describe the retained hidden file. For a verified
   rollback, terminal cleanup must be crash-safe under the shared lock,
   including interruption between retiring the anchor and receipt.
   Never replay publication during recovery. The orphan stage/partial
   receipt window before successful prepare is deliberately retained
   for review, not automatically adopted or deleted. No target effect
   occurs before publication.

This is a narrower primitive than the complete policy design. Before
integration, resolve the existing planner's refusal of any relevant
drop-in directory: the #97 planner increment observes a sole, exact,
protected empty local drop-in directory for a selected permanent-MAC
rule with unspecified WOL. It refuses duplicate/earlier/global
directories, nonempty/unsafe directories, reported drop-ins, and
changed directory or rule observations. No publication permission is
given. The controller must independently re-walk and revalidate these
conditions under the shared lock. Creating a new directory requires
its own durable ownership/recovery mechanism. Broader support for
generic/default policies remains separate.

Directory descriptors do not prove that the directory is still bound to
the live policy pathname. The future controller must independently
revalidate that binding, the base rule and policy inventory, exact
permanent NIC identity and separate consent. There is no atomic
compare-and-unlink operation against an uncooperative privileged
writer; the primitive assumes the shared exclusion domain and protected
directories. It must not claim resistance to arbitrary concurrent root
mutation. Even under that assumption, observed replacements, edits,
extra links and mismatches refuse recovery. Moving the target to a
hidden quarantine name before inspecting it could narrow the final
check/unlink race, but also moves potentially foreign policy and adds
a crash window and a second restoration conflict. Do not introduce
that sequence without a separately journaled rename/no-clobber
restoration protocol and review.

The receipt now avoids mount-local st_dev, which can change across
Btrfs subvolume mounts or device-mapper re-enumeration. f_fsid is
additional opaque filesystem evidence, NOT a guaranteed persistent
UUID. Upstream Linux commit c2a74ed0494c2736486b49c52767b2f50b83425f
(Btrfs f_fsid derivation) incorporates backing dev_t for single-device
filesystems to distinguish clones. Consequently a reboot, a device
change, kernel change or cloned filesystem may still change or
invalidate this evidence. Do not accept inode numbers alone or silently
ignore an fsid mismatch. A missing or replaced anchor invalidates
ownership evidence. A verified persistent filesystem/subvolume identity
provider may be needed for the production controller if f_fsid is
unstable on supported hosts. Re-walk the fixed trusted paths without
following symlinks after restart; compare the actual directory binding
before any effect. This increment fails closed on identity mismatch;
it does not yet establish universally reboot-safe recovery. Before
integration, measure st_dev, f_fsid, inode and hard-link count across a
normal reboot in throwaway directories on the actual filesystem,
including Btrfs. No forced reboot or live network changes.

The test matrix covers no-clobber publication, protected receipt
validation, ownership conflicts, dangling links, metadata/contents
changes, directory identity, fsync failure windows before and after
publication, recovery without forward replay and idempotent undo. Tests simulate
renumbered st_dev with unchanged f_fsid, reject changed/missing fsid
and old receipt schemas, and verify that raw filesystem errors do not
expose private entry names.
Fault injection simulates errors, not a physical power-loss durability
test. Before production use, exercise the complete journal and cleanup
protocol across actual supported filesystems and restart/remount
boundaries. No tests against the live network policy are required here.

## Experimental filesystem identity provider (#98)

`scripts/wol_fs_identity.py` is a separate private read-only probe,
not yet a replacement for schema 2 publication receipts. It accepts
an open regular-file/directory descriptor, identifies its mount
through the descriptor's mnt_id in /proc/self/fdinfo and the matching
/proc/self/mountinfo record, and only attempts ext4, XFS or Btrfs.
The first implementation restricts ioctl encodings to the verified
64-bit asm-generic ABIs x86_64, aarch64 and riscv64. It uses the
17-byte FS_IOC_GETFSUUID struct from Linux UAPI (introduced with the
Linux 6.9 VFS UUID work; actual support is probed, not inferred from
version) and, on Btrfs, the special unprivileged BTRFS_IOC_INO_LOOKUP
query with treeid=0/objectid=256 to obtain the containing subvolume.
Sources:
https://github.com/torvalds/linux/blob/master/include/uapi/linux/fs.h
and https://btrfs.readthedocs.io/en/stable/btrfs-ioctl.html.

The resulting private comparison tuple contains filesystem type,
16-byte nonzero UUID, Btrfs subvolume ID where applicable and inode.
Repeated UUID/subvolume/mount observations and a second fstat must
agree within the query. Missing /proc evidence, unknown filesystems
or ABIs, unsupported ioctls, inconsistent observations and malformed
responses return no identity. There is no fallback to st_dev or
f_fsid, no device enumeration, no shell command, and no public
serialization. This is candidate evidence, not a universal unique
identity: UUID clones, restored images, subvolume recreation and
inode reuse remain limitations. Retain the anchored hard-link checks
and protected fixed-path revalidation. The existing publication
receipt format is unchanged until the provider and actual filesystems
have passed independent review and physical acceptance. On older
kernels without the UUID ioctl, persistent WOL mutation must remain
unavailable unless a separately reviewed stable provider is added.
No agent installation dependency on this experimental feature.

Fixture tests pin the ioctl layout, mount-ID matching, subvolume
distinction, failure paths and no fallback. Before integration compare
the probe's private identity, st_dev, f_fsid, inode and link count
across a normal reboot on disposable Btrfs files, then validate ext4
and XFS/LVM. Do not share raw UUIDs or change live network policy.

## Test and integration sequence

- Review the service-state hardening and tests first.
- Implement protected WOL before-state validation and no-clobber
  publication/recovery in filesystem fixtures; cover failures at each
  fsync/publication/receipt boundary, unsafe paths, changed NIC and
  policy, concurrent destination creation, and ownership ambiguity.
- Review the shared journal operation dispatch and compatibility
  before production mutation or root request exposure.
- Implement separate wizard consent and fixed redacted status;
  distinguish preserve, review required, configured pending reboot,
  rolled back and recovery required.
- Physical positive mutation requires suitable isolated test hardware
  or a VM with relevant NIC support; preserve the already working
  Gentoo rule. Do not deliberately break the operator's primary host.
- Validate NetworkManager separately before its writable backend.

No existing network settings are modified by this design or by the
service-state hardening increment.
