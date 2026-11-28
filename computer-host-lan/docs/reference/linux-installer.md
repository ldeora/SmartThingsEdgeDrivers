# Linux installer engineering reference

This is the current protected standalone installer contract, not installation
instructions. See [install on Linux](../install-linux.md) and [maintenance](../upgrade.md).
Production uses the schema-1 transaction journal. Request schema numbering,
journal schema numbering and experimental schema-2 primitives are distinct.
The current release is unsigned; the user must verify a trusted release
before executing it. No developer checkout is an authorized root payload.

## Components and trust boundary

| Source | Responsibility |
| --- | --- |
| linux-installer/application.go, install_ui.go, maintenance_screen.go | One interactive application: menu, inspection, setup, review and consent |
| framed_input.go, terminal_handoff.go | Revocable input ownership and restored terminal before authorization |
| cli.go | Noninteractive explicit action, fixed arguments and redacted result |
| installer_api.py, installer-api.sh | Read-only inspection/plan/runtime observations |
| bundle.go, bundle/, sync_bundle.py | Fixed embedded sources and manifest parity |
| protected_handoff.go, bootstrap.go | Verify staged executable bytes, protected elevated handoff, helper promotion and recovery routing |
| installer-entry.sh, installer_root.py | Installed-only interpreter and request/manifest validation |
| installer_transaction.py, install_core.py | Shared lifecycle engine, managed plan, service state, snapshots and rollback |
| payload_staging.py, transaction_journal.py | Protected durable staged bytes and write-ahead authority |
| credential_continuity.py, runtime_verify.py | Private same-process metadata comparison and redacted runtime gate |
| historical_snapshot.py, retained_state_eligibility.py | Local historical selection and explicit legacy reuse eligibility |
| persistent_wol.py, wol_ownership.py | Bounded NIC policy plan, apply/reversal and ownership evidence |

Trust the verified publisher/build, system Python, kernel, root and protected
filesystem; this is not a sandbox against malicious root or compromised
build authority. The ordinary-user wizard/CLI performs read-only preflight.
A plan is neither authorization nor a lock reservation. Demo does not
inspect the host; live preview does not elevate. Discovery does not
authenticate or pair a hub. Legacy mutating source shell entry points
refuse, including attempts to bypass protected adoption. Only the current
protected engine mutates managed host state.

### Authorization and executable handoff

The full-screen application returns an operation only after review and
literal confirmation. Stop the program, revoke and join its input ownership
and restore/check terminal settings before any privilege prompt. Never let a
stale Bubble Tea/Ultraviolet read consume a password or shell input.
Passwords are handled by the OS, not the installer. Accessible mode uses
plain prompts with the same consent boundary; noninteractive CLI requires
supported already-authorized elevation, never waits for a password.
Interactive sudo/doas/run0/terminal su support is explicit; do not retry
another provider after denial.

The protected handoff snapshots the running executable, binds its digest and
copies/checks it in root-private storage before root execution; never run
a caller-writable extracted Python tree as root. The root bootstrap validates
the embedded allowlist, prepares the installed helper under
/usr/libexec/computer-host-lan and uses only fixed system interpreter
locations (Python 3.10+, isolated -I -S -B). No elevated custom Python,
source paths, shell commands or credential paths from callers. The installed
helper and payload manifest are validated for trusted ownership and
permissions. Do not replace a helper beneath an incomplete transaction;
status/recover use the existing compatible helper. A missing helper is not
proof that no journal/staging evidence exists.

### Requests and results

The Go/Python boundary uses bounded, exact-key, versioned JSON with duplicate
keys rejected. Schema 1 covers status/recover and install/upgrade/repair,
with explicit power preserve/enable/disable and optional validated interface;
install-like extensions bind reviewed reuse and WOL choices. Schema 2 wire
requests cover uninstall, backups, restore (name/digest), wol-check and
wol-remove. These do not imply a schema-2 production journal. Inspect/plan
reports read-only observations, not verified installation or connectivity.
Do not pass arbitrary paths, environment or shell fragments to privileged
operations. See parse_request and privilegedRequest.validate for exact
accepted fields; new fields require coordinated validation and compatibility
tests.

Results contain fixed status/error/recovery/identity/continuity enums,
secrets_included=false and optional WOL outcome. Never echo exceptions,
UUID, key, credential metadata, MAC, IP, interface/profile identifiers or
private journal content. Validate runtime version before reporting it.
CLI exit status: 0 completed, 1 failure/unknown, 2 invalid invocation,
3 outstanding recovery/cleanup. Lost reply after authorization is not proof
of no mutation. Status is not permission to recover an active transaction.

## Exclusive ownership and durability

| Fixed path | Purpose |
| --- | --- |
| /run/computer-host-lan/bootstrap.lock | Root-private lifetime exclusion across helper promotion/execution |
| /run/lock/linux-host-agent-install.lock | Shared lifecycle exclusion |
| /var/backups/linux-host-agent/wizard-transactions/lock and journal.json | Protected journal |
| /var/lib/computer-host-installer/staging/stage.lock | Staging coordination |
| /var/backups/linux-host-agent/snapshot-* | Private managed-file snapshots |
| /usr/libexec/computer-host-lan and controlled siblings | Installed helper and bounded promotion/rollback |

Respect the lock ordering and hold ownership across each transition. Do not
drop/reacquire exclusion between eligibility and mutation; do not unlock an
inherited lock in a child. Existing directories/files must pass owner,
mode, type, link and no-follow checks; never normalize unsafe administrator
state to make it eligible. Shared legacy lock availability is a separate
risk from authorization.

The schema-1 journal records a fixed transaction ID, operation, stage and
snapshot references and legal phase transitions. Before mutation:

1. Acquire exclusive ownership, validate existing protocol/service state
   and fixed request. Create INSPECTED and bind the allowlisted staged
   payload to the transaction. Stage files are data, not authorization.
2. Persist STAGED and the private before-state snapshot (bounded fixed
   managed paths, types, ownership, permissions, service state). Sync the
   snapshot before SNAPSHOTTED.
3. Persist APPLYING before changing managed files, account/marker or
   service state. Apply the fixed plan; sync affected directories bottom-up.
4. ACTIVATING then VERIFYING: activate and validate the expected service,
   socket, managed files and matching runtime where applicable; verify
   retained credentials in the original process.
5. Persist COMMITTED only after successful gates. Retire stage and journal
   durably; a valid committed operation with cleanup pending is not a
   failed operation. No forward replay after interruption.

Use bounded regular files, exclusive/no-replace publication where required,
atomic rename and directory fsync. Validate exact allowed paths and
digests. A temporary record is not a durable transition; never promote an
uncommitted candidate simply because it is complete. A durable VERIFYING
predecessor plus uncertain COMMITTED temp requires rollback, not commit.
Recovery under a valid visible terminal record performs terminal cleanup
only. Partial/ambiguous journal or stage evidence is retained unless the
current checked schema and retirement guard establish safe cleanup.
Unknown schema and unsafe ownership fail closed.

## Operation and recovery policy

The managed file allowlist is defined by MANAGED_PATHS in install_core.py;
see the [installation inventory](../install-linux.md#whats-installed-and-what-stays-on-uninstall).
It does not authorize entire directory deletion or arbitrary system unit
changes. Supported stable service state (active/enabled versus stopped/
disabled) and managed file content/modes are rollback scope; transitional
or unsafe service states are refused/normalized rather than promised exact
reconstruction. Inspect/plan do not install. The engine does not change
firewalls, start Avahi, pair a device or bounce networking.

| Operation | Contract |
| --- | --- |
| Install / upgrade / repair | Fixed bundled payload, explicit power policy and validated interface selection; preserve custom state and credentials |
| Uninstall | Verify managed service/socket stopped and disabled, remove only managed files and verify enablement absence |
| Recover before APPLYING | Abort and retire staged data; never start forward install |
| Recover after APPLYING | Restore the validated current-before snapshot, service state, verify/sync and persist ROLLED_BACK |
| Recover terminal | Finish cleanup without reversing a committed outcome |
| Historical restore | Explicit selection of eligible local snapshot; capture a new current-before snapshot, apply only recorded managed state, verify and retain identity/key/WOL |
| Reuse retained legacy v2 state | Explicit REUSE after independent eligibility checks under lock; normal install plan, not arbitrary adoption |

Account, owner marker, private identity/key, local snapshots and protected
helper are intentionally retained on uninstall and rollback where created.
First start may create previously absent credentials; it is not promised
that rollback returns an entirely pristine OS. If installation/recovery
cannot be verified, preserve the evidence and return recovery_required;
never delete journal, backups or state to unblock setup. The status/cleanup
path must not claim success simply because a subsequent file check passed.

### Credential continuity

Private files installation-id and control-token under /var/lib/linux-host-agent
are agent-owned and excluded from managed snapshots. Never replace, copy,
restore, log or regenerate existing credentials to make installation succeed.
Use no-follow observation of directory/account and file metadata before
APPLYING and before terminal COMMITTED or ROLLED_BACK in the same process.
Compare device/inode, mode, owner, size, mtime/ctime and relevant link state;
distinguish absent/new files from retained files. Account mapping and
directory permissions must remain valid. First-start temporary hardlink
publication needs its narrowly allowed treatment; unexpected hardlinks
or unstable observation are unsafe.

No credential values/hashes or baseline are persisted or returned.
Metadata verification under trusted root is not cryptographic content proof.
A new recovery process cannot recreate the original baseline: report
not_verified even after successful managed-state rollback. Do not relabel
a failed continuity comparison as verified by later health checks. Durable
cross-interruption/reboot credential continuity is a later scope (#152).

### Historical local restore and retained-state reuse

Historical restore is not recovery. Select by bounded snapshot basename and
reviewed digest, reject traversal, links, unexpected files, invalid sizes,
modes, protocol or incompatible service state. Protected local backups
are validated as eligible v2 managed-file snapshots, never executed as
source. A digest binds selection; it is not independent publisher
authentication. The new journal points to the current-before snapshot,
not the selected historical source. Preserve existing ID/key and independently
configured persistent WOL; restore recorded interface pin when present,
leave unrecorded optional files unchanged. Interrupted restore rolls back
rather than replaying the historical operation.

Retained rc.2 state without registered agent is not clean install. Reuse
requires explicit consent and validated private layout, account, UUID/key,
stopped service state and compatible v2 backup evidence under the same
exclusion domain. Evidence supports protocol provenance, not cryptographic
binding of a key to a backup. Refuse v1, unknown or ambiguous state, unsafe
links/modes and outstanding recovery. Do not forge a marker or regenerate
identity to force adoption. Keep the existing SmartThings device.

## Persistent Wake-on-LAN

WOL is optional and separate from authenticated power. Fresh setup with
suggested wired NIC defaults Configure; upgrade/repair defaults Keep.
Keep/leave never write persistent or runtime WOL. Interface pinning alone
changes the agent's reported interface, not NIC wake policy.
Ordinary-user capability unknown (including permission denial) is not
unsupported. The privileged check independently validates the selected
physical wired adapter and visible reviewed policy. Confirmed unsupported
or unavailable capability returns unsupported/capability_unknown, permits
agent install and skips the pin; unsafe/changed policy is different and
refuses the proposed change. Fresh wizard may explicitly review leaving
WOL unchanged when optional preview unavailable. Do not suppress arbitrary
preview errors or silently authorize a different change.

Supported writable scope is the selected wired NetworkManager Ethernet
profile or a safe per-permanent-MAC systemd .link rule. Confirm actual
default-route/interface/profile selection and existing policy; do not
overwrite complex, conflicting or unknown administrator policy. Preserve
unrelated flags/settings, never activate a connection, restart networking
or alter routes. Apply magic wake immediately with ethtool where supported.
Do not mistake combined flags or unreadable capability for a safe policy.
Review binds exact visible policy/digest, then root replans under lock.
No mutation before durable transaction authority for install-like work.

Maintain root-private ownership records across restart, reboot, upgrade,
uninstall and reinstall. Ownership is not established by matching bytes
alone. Only reverse the installer's own known change after revalidation;
never clobber changed policy or use stale ownership to authorize a
different adapter/profile. On agent rollback, attempt WOL reversal but
do not prevent managed-agent recovery if WOL compensation fails.
Retain ownership evidence, report wol_review_required without leaking
network details. Do not treat unresolved NIC policy as permanent agent
recovery lock. Independent check/remove requires a clean journal and same
shared exclusion; REMOVE is explicit. Normal uninstall preserves WOL.
Separate removal must not reinstall or modify agent services.

## Evidence and scope boundaries

| Required invariant | Implementation / representative regression suite |
| --- | --- |
| I1 exclusive ownership; I2 durable write-ahead before mutation | installer_transaction.py, transaction_journal.py; test_installer_transaction.py, test_transaction_journal.py |
| I3 independent trust; I12 protected elevated execution | protected_handoff.go, bootstrap.go, installer_root.py; Go handoff/bootstrap tests, test_installer_root.py, test_installer_protocol_guard.py |
| I4 immutable bounded stage/snapshot intent; I5 compatible recovery | payload_staging.py, transaction_journal.py; test_payload_staging.py, test_transaction_journal.py |
| I6 no forward replay; I7 explicit rollback/retention; I8 verified outcome | installer_transaction.py, runtime_verify.py; test_installer_transaction.py, test_runtime_verifier.py |
| I9 preserve ambiguous evidence; I10 durable cleanup | journal/stage retirement checks, fault-injection tests; test_transaction_journal.py, test_payload_staging.py |
| I11 retained metadata continuity | credential_continuity.py; test_credential_continuity.py |
| Historical selection/reuse | test_historical_snapshot.py, test_retained_state_eligibility.py, transaction tests |
| WOL ownership and parity | test_persistent_wol.py and native NetworkManager property smoke; physical tests still needed per platform |
| Terminal ownership | framed_input.go, terminal_handoff.go, Go PTY integration/stress |

The source contains experimental restore_adopt_* and wol_fs_* primitives and
their tests. These are not a second production installer or permission to
activate schema-2 journals. The current schema-1 journal does not bind
all schema-2 immutable intent/receipt semantics; mixed-version initial
write ambiguity, durable filesystem identity and cross-reboot continuity
need separate compatible design and qualification. Do not infer reboot-
stable identity from mount-local st_dev or f_fsid alone, including Btrfs.
Never weaken fail-closed handling or existing fixture tests during cleanup.
Formal signing and independently authenticated attestation integration
remain deferred under current release scope; ordinary SHA-256 integrity
does not authenticate a publisher.

Test on disposable roots or native CI without real authenticated power
requests. Fault-injection fixtures are not proof of arbitrary physical
power-loss durability. Real Gentoo results establish only the exact
reported build/platform; second Linux and Windows acceptance remain
separately tracked in [issue #119](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/119).
See [development and release process](../development.md).
