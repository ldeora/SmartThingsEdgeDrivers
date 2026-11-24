# Computer Host LAN — current Linux installer architecture

**Development implementation, not a published installer.** Architecture audit baseline `1a716b4` (after #147).
Published rc.2 still uses the legacy shell engine. See
[convergence](LINUX-INSTALLER-CONSOLIDATION.md) and
[release authentication](LINUX-INSTALLER-RELEASE-AUTHENTICATION.md) for #101/#84.

## Components and privilege boundary

| Component (relative to computer-host-lan) | Role |
| --- | --- |
| linux-installer/main.go, live.go, install_ui.go | Demo, read-only preflight, interactive confirmation and completion |
| linux-installer/cli.go | Explicit actions, configurable plan, sanitized results |
| scripts/installer-api.sh, installer_api.py | Unprivileged inspection and fixed prospective file plan |
| linux-installer/bundle.go, bundle/, sync_bundle.py | Fixed embedded source set, manifest generation and parity |
| linux-installer/bootstrap.go | Root bootstrap, lifetime lock, helper promotion and recovery routing |
| scripts/installer-entry.sh, installer_root.py | Installed-only Python selection, schema and manifest validation |
| scripts/installer_transaction.py | Common transaction engine |
| scripts/payload_staging.py, transaction_journal.py | Protected staged bytes and journal |
| scripts/install_core.py, runtime_verify.py | Fixed file plan, snapshot, restore and runtime verification |
| agent/ | Agent, power helper, systemd and Avahi definitions |

The ordinary-user wizard and CLI share read-only checks and plans.
Demo does not inspect. Plain live preview uses a selected external API;
real wizard uses embedded inspector by default, CLI exclusively.
The inspector validates bounded output, fixed paths and enums. Local
mDNS discovery in interactive modes does not authenticate/pair a hub.
CLI does not browse. A plan is neither authorization nor a reservation.

Explicit confirmation precedes modifying actions. Interactive authorization
supports sudo/doas/run0/terminal su; CLI uses noninteractive sudo/doas/run0.
No fallback after a refusal. The internal root bootstrap executes the
selected Go binary, checks the embedded bundle and prepares root-owned code
under /usr/libexec/computer-host-lan. The installed shell uses fixed system
PATH and Python 3.10+ with -I -S -B. The helper validates selected command
and protected manifest; caller cannot supply arbitrary source, Python,
shell command or private state path. Status/recover use existing installed
helper rather than promoting a new one.

## Protocol and results

Inspect/plan schema 1 is read_only. Plan lists fixed managed paths and
prospective operations, changes_applied/runtime_verified false, privileged
transaction state unknown. CLI reports validated prerequisite checks and
conservative preflight network observations, not verified connectivity.

Go root request schema 1: action status/recover/install/upgrade/repair,
power preserve/enable/disable for install-like actions, optional validated
interface name. No installation options for status/recover. Schema 2 is the
exact two-field uninstall request. Internal Python handoff adds fixed trusted
source and hashes, not user inputs. Result schema 1 has fixed status,
operation, error, recovery and identity enums, secrets_included false.
CLI adds its own fields outside the privileged protocol. Exit 0 completed,
1 failure/unknown, 2 invalid invocation, 3 outstanding transaction or cleanup.
A lost reply after authorization starts is not evidence of no mutation.
Status exit 3 does not authorize recovering an active transaction.

## Locks and lifecycle

| Fixed path | Purpose |
| --- | --- |
| /run/computer-host-lan/bootstrap.lock | Root-private lifetime lock across promotion and execution |
| /run/lock/linux-host-agent-install.lock | Shared manual/protected lifecycle exclusion |
| /var/backups/linux-host-agent/wizard-transactions/{lock,journal.json} | Protected journal |
| /var/lib/computer-host-installer/staging/stage.lock | Protected staging exclusion |
| /var/backups/linux-host-agent/snapshot-* | Managed-file snapshots |
| /usr/libexec/computer-host-lan and controlled siblings | Installed helper, next/previous/failed sets |

Go holds the lifetime lock across promotion and execution. Promotion checks
the shared lock and protected status; Python takes the shared lock, then
journal and staging coordination. Do not remove locks or bypass outstanding
transactions. The shared legacy lock has a tracked availability risk (#79).

INSPECTED → STAGED → SNAPSHOTTED → APPLYING → ACTIVATING → VERIFYING →
COMMITTED. Stage bounded hashes and bind to journal, sync snapshot before
SNAPSHOTTED, begin managed mutation only after durable APPLYING. Recheck
v1/v2 provenance and service state under lock. Write v2 intent marker,
ensure account, apply managed plan, sync directories bottom-up, activate
systemd and verify managed files/services/runtime/identity as applicable.
Only verified success reaches COMMITTED.

Pre-apply recovery aborts and cleans staging; applied recovery restores
validated snapshot and service state, verifies and syncs before ROLLED_BACK.
Terminal recovery only cleans, never resumes forward work. An uncertain
COMMITTED candidate with a durable VERIFYING predecessor is rolled back,
not promoted; a visible valid terminal COMMITTED record follows the
schema-1 terminal cleanup policy. Failure retains recoverable evidence. Committed with cleanup pending is not failed install.
Never replace a helper beneath incomplete recovery. Historical snapshot
restoration is a different operation, not yet protected CLI functionality.

## Operation scope and retained state

Install/upgrade/repair modify only managed agent files, systemd service/socket,
known drop-ins and optional Avahi service; account and v2 intent marker as
needed. Upgrade preserves settings unless explicitly selected. Uninstall
verifies stopped/disabled managed units before removal. It retains private
identity/key, account, marker, snapshots, protected helper and operator
network policy. Recover restores or cleans; plan/status do not install
(status may initialize bootstrap coordination). No automatic pairing.

The exact managed-file allowlist (MANAGED_PATHS in install_core.py) is:

- /opt/linux-host-agent/linux_host_agent.py
- /opt/linux-host-agent/power_helper.py
- /etc/systemd/system/linux-host-agent.service
- /etc/systemd/system/linux-host-agent-power.service
- /etc/systemd/system/linux-host-agent-power.socket
- /etc/systemd/system/linux-host-agent.service.d/enable-power.conf
- /etc/systemd/system/linux-host-agent.service.d/90-wol-interface.conf
- /etc/avahi/services/linux-host-agent.service

This does not authorize management of entire directories or other unit
files. The owner marker is /var/lib/linux-host-agent-installer/protocol;
private installation-id and control-token live under /var/lib/linux-host-agent/. Snapshots do not contain
credentials. Root-side identity verification may read the UUID but never
reports it. UUID preservation does not establish key equality or pairing.
No automatic firewall edits, persistent NIC WOL or arbitrary network
policy writes. Interface pinning affects agent configuration only.
WOL publication/identity primitives (#88/#98) have no production caller.

## Threat model and limitations

Trust publisher, reviewed workflow, system Python, kernel and root-controlled
filesystem. A verified user-writable binary can still be replaced before
elevation; use protected paths and independently authenticated bytes.
The adjacent test artifact checksum does not authenticate the publisher.
Fixed paths, ownership checks and no-follow opens fail closed; not a
sandbox against hostile root, malicious firmware or compromised build authority.
The published legacy shell engine has weaker journal/recovery/service/runtime
guarantees. The intended stable design is one authenticated executable
and one engine; shell cutover is pending. Fixture/CI and supervised Gentoo
tests are not final-release, other-distribution or power-loss certification.

## Consolidated safety invariants and schema-1 release audit

Audit baseline: `1a716b4` after #147. This is a source/fixture review of
the development schema-1 journal engine (install/upgrade/repair/uninstall/
recover), **not** acceptance of the published rc.2 manual engine or a
production authorization. Schema-2 restore/adopt remains fixture-only.
The Go/Python request protocol numbering is distinct from journal schema
numbering (the uninstall wire request is schema 2).

| ID | Required invariant | Schema-1 audit disposition |
| --- | --- | --- |
| I1 | Exclusive transaction ownership; one controller, ordered locks | Supported in existing protected Go/Python engine: bootstrap lifetime, shared manual, journal, stage locks. Shell convergence and live handoff acceptance pending #101; #151 addresses future schema-2 composition. |
| I2 | Durable write-ahead authority before mutation | Supported by current phase order and fault-injection tests: stage/snapshot durability, APPLYING before managed/service/account/marker changes, directory sync before commit. Physical crash durability not certified. |
| I3 | Independent trust, not journal/digest alone | Internal manifest and bounded fixed source checks supported; independent publisher authentication and protected elevated handoff pending #84 (I12). |
| I4 | Immutable intent/evidence binding | Transaction ID, fixed phase progression, protected stage and snapshot reference supported within trusted-root model. Schema 1 does not bind complete immutable intent or snapshot hashes into the journal, and recovery does not consume the #116 provenance receipt; do not claim schema-2-level binding. Review compatibility with #155 rather than expanding schema-1 recovery silently. |
| I5 | Compatible recovery; unknown schema fails closed | Schema-1 parser rejects unknown durable record schemas, helper checks installed status before normal promotion. Ambiguous initial prefixes are a demonstrated mixed-version exception (#148); #150 handles missing helper provisioning. Do not enable schema 2. |
| I6 | No automatic forward replay | Supported: pre-apply abort, applied rollback, terminal cleanup. An interrupted COMMITTED temp with durable VERIFYING is not a commit; roll back. Do not reverse a valid terminal committed uninstall merely to clean up. |
| I7 | Explicit recovery policy for every permitted mutation | Managed files and service state restored/verified; uninstall checks quiescence and enablement absence. Account/owner marker and private state deliberately retained, not part of rollback snapshot. Credential verification gap #155; document retention below. |
| I8 | Terminal outcome independently verified | File/service and active-runtime gates exist; stopped agent uses file/service checks without HTTP. Rollback uses snapshot and service checks. Actual credential continuity not covered (#155); full physical outcome acceptance pending. |
| I9 | Preserve uncertain evidence | Same-schema recovery validates initial orphan prefixes and uses protected write-ahead phase/verified outcome for retirement of leftover temps; not the stricter schema-2 prefix policy. Mixed-version ambiguity blocked by future #148; v2 final discard guard #149. |
| I10 | Durable cleanup after verified retirement | Supported by stage retirement and terminal journal cleanup, sync/retry tests. No assertion of arbitrary filesystem corruption or sudden-power-loss recovery; review on supported physical filesystems. |
| I11 | Retained UUID and control-token continuity | **Gap reproduced, proposed v1.0 P0 #155.** UUID runtime comparison requires an active agent; uninstall checks disk UUID; token is not compared and rollback does not independently establish continuity. |
| I12 | Independently authenticated elevated execution | **Open v1.0 gate #84.** No authenticated release or accepted protected executable handoff yet. |

"Supported" is a bounded source/fixture assessment, not release PASS.
I1/I5 are sound in the supported single-schema protected engine, not
proof of mixed-version safety or completed #101. For I4/I9, root-controlled
protected storage and cooperating writers are explicit assumptions; the
schema-2 evidence model is not retroactively required for every schema-1
operation. Do not convert a difference in scope into an unsupported
security claim.

### Explicit schema-1 mutation and retention policy (I7)

Managed application/unit/drop-in/Avahi bytes and modes and supported
stable active/enabled service state form the rollback scope. Failed/
transitional states are normalized or refused, not promised to be
recreated exactly. Uninstall verifies stopped/disabled units (including
the power helper) and managed enablement absence before success.
The service account and v2 owner marker intentionally persist after
rollback and uninstall, including first-install recovery, so retained
private state remains attributable to this installer. This is a policy,
not an accidental incomplete rollback. The existing engine does not
delete the account, marker or private credentials to recreate a pristine
machine; a first start can create previously absent ID/key state.
Snapshots and protected helper are retained as recovery resources.
No installer mutation of operator-managed NIC WOL or network policy is
authorized. Document and verify the exact retained-state behavior for
first install, repair, uninstall and failed activation. Existing ID/key
must not be replaced; absence/new creation is a separate condition.
See #152 and #155.

### Credential continuity (I11) evidence

Disposable-root probes used the real InstallerBackend with simulated
service operations and runtime health observations, not real systemd or
a claim that the agent normally rewrites credentials:

| Injected change | Observed result |
| --- | --- |
| Active upgrade: token rewritten, UUID unchanged | installed / verified; journal cleared |
| Stopped upgrade: UUID rewritten | installed / not_verified; journal cleared |
| Uninstall: token rewritten, UUID unchanged | uninstalled / verified; journal cleared |
| Failed upgrade: token rewritten during rollback | rolled_back; journal cleared |

These demonstrate missing detection, not spontaneous credential changes.
The normal agent persistent_value publishes only absent credentials
without replacing an existing file, and the installer managed allowlist
excludes both credentials. Proposed remedy (#155): capture protected
metadata continuity before APPLYING and check it before terminal success
and during recovery. Use reboot-stable filesystem/subvolume identity
(#98), inode/size/mode/owner/mtime/ctime, no credential value or hash.
Account for legitimate first-start hard-link leftovers and distinguish
absent/newly created credentials. Metadata is continuity evidence under
the trusted-root/cooperating-writer model, not cryptographic content
proof. The historical receipt reader enforces the exact #116 receipt
schema/key set; an extension needs a reviewed compatible version or
separate protected sidecar. Do not assume a journal schema unchanged
means all readers are compatible.

### Consolidated review findings and release boundary

| Finding | Tracking | Scope |
| --- | --- | --- |
| A: mixed-version initial-write ambiguity | #148 | Before schema-2 activation; durable staging fence before first journal byte, retire last. Test archived helpers. Complete fence-only state needs explicit independently verified recovery; partial fence remains evidence. |
| B: final reconciliation check inconsistency | #149 | Fixture hardening; not a v1.0 dependency. |
| C: absent current/previous helper does not prove absence of evidence | #150 | Narrow read-only Go check opportunistically before rc.3; full compatible provisioning before schema divergence. |
| D: nested manual lock in eligibility/transaction | #151 | Schema-2 ownership context; do not release lock between eligibility and begin. |
| E: rollback scope/credential continuity | #152, #155 | Narrow schema-1 continuity gate; broader schema-2 contract separately. |
| F: shared exclusive no-replace publication | #153 | Opportunistic defensive hardening; no replacement fallback. |

**Proposed release split:** v1.0 is the independently authenticated Go
wizard and CLI, with supported schema-1 install/upgrade/repair/uninstall/
recover behind one engine (#101/#84), including supported shell-entry
point migration and explicit refusal of unsupported options. No silent
fall back to manual restore or adoption. Schema-2 restore/adopt is
proposed for 1.1, subject to separate acceptance, not a stable 1.0 gate.
Persistent WOL remains separate (#88/#98). The stable gates and published
rc.2 assets/instructions remain unchanged until approved cutover. Neither
the audit nor the proposed version split authorizes a release.

Next: finish #149 independently, design/implement #155 with independent
review, take the narrow #150 check if suitable before rc.3, complete
#101 supported entry point convergence and #84 authentication, and
reconcile the remaining rc.3 fixes and release triage with
[stable gates](../release/V1-RELEASE-GATES.md),
[readiness](../../RELEASE-READINESS.md) and
[physical acceptance](../release/RC-ACCEPTANCE.md).
Do not waive real Windows/Linux acceptance, licensing/signing, channel
assignment or seven-day soak. Review #131 CI Lua execution separately:
the local non-root standalone archive run had four expected skips
(two missing monorepo workflows, one unannounced-RC-only test, one
root-only cross-UID test); all ten test_lua modules' discovered tests
passed in the focused local run, no skips there. This does not establish
Lua execution in every CI job. Go source reviewed; local Go 1.23.2 is
below the required 1.25.8; Go validation remains CI/reviewer-only.
No live-host change or physical release certification in this audit.

## Historical design notes

Earlier implementation records remain available in this directory. Their
future-tense descriptions are historical, not current status:
- [LINUX-GO-INSTALLER-INTEGRATION](LINUX-GO-INSTALLER-INTEGRATION.md)
- [LINUX-INSTALLER-API](LINUX-INSTALLER-API.md)
- [LINUX-INSTALLER-DESIGN](LINUX-INSTALLER-DESIGN.md)
- [LINUX-INSTALLER-PRIVILEGED-RECOVERY](LINUX-INSTALLER-PRIVILEGED-RECOVERY.md)
- [LINUX-INSTALLER-TRANSACTION-BACKEND](LINUX-INSTALLER-TRANSACTION-BACKEND.md)
- [LINUX-JOURNALED-UNINSTALL](LINUX-JOURNALED-UNINSTALL.md)
- [LINUX-PARITY-ACCEPTANCE](LINUX-PARITY-ACCEPTANCE.md)
- [LINUX-PRIVILEGED-STAGING](LINUX-PRIVILEGED-STAGING.md)
- [LINUX-TRANSACTION-JOURNAL](LINUX-TRANSACTION-JOURNAL.md)

Current persistent WOL design: [LINUX-WOL-TRANSACTION-DESIGN.md](LINUX-WOL-TRANSACTION-DESIGN.md).
