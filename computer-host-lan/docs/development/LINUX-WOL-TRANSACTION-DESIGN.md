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
rollback verification. An existing installation must expose loaded stable
active/inactive and persistent enabled/disabled states for both the agent
and its power socket. A fresh install requires explicit absence of both.
Transitional, masked, failed, runtime-only, partially missing or unknown
states cannot be represented faithfully by the existing boolean snapshot
schema and must abort before application. A stopped agent still skips
HTTP health verification, not service verification. Rollback of a fresh
install requires explicit absence; rollback of an existing installation
requires loaded units with the original stable states.

This change does not alter the snapshot schema, activation commands,
manual installer semantics, root protocol, WOL policy, or network settings.
A legacy snapshot from an unusual partial installation may now need manual
recovery instead of an unsupported claim of successful restoration.
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
transaction or clean up its snapshot. Test upgrade, downgrade and
interruption boundaries before wiring a new root request.

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
