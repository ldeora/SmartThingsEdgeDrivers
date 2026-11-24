# Computer Host LAN — current Linux installer architecture

**Development implementation, not a published installer.** Current after #112.
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
Terminal recovery only cleans, never resumes forward work. Failure retains
recoverable evidence. Committed with cleanup pending is not failed install.
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

Managed paths: /opt/linux-host-agent/, /etc/systemd/system/ and
/etc/avahi/services/linux-host-agent.service. The owner marker is
/var/lib/linux-host-agent-installer/protocol; private installation-id and
control-token live under /var/lib/linux-host-agent/. Snapshots do not contain
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
