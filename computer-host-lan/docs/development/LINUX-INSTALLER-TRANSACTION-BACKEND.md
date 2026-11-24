# Linux installer PR #76 — Transaction backend and shared installation lock

> **Historical design note:** Describes the implementation at its original milestone. For current behavior, see [Linux installer architecture](LINUX-INSTALLER-ARCHITECTURE.md).

**Scope:** root-side controller library and fixture tests, not an elevated
wizard or live installing product. No user-visible agent, Edge Driver,
systemd, credentials, firewall, WOL, networking, or hub state is modified
by this PR.

## Why this change

PRs #73–75 added runtime verification, a protected journal, and verified
payload staging. This PR combines them into the **actual installation
transaction sequence** and coordinates with the working manual Linux
installer. The backend exercises the real install_core file-plan, snapshot,
apply and restore functions inside disposable test roots. The systemd
boundary is a separate adapter so tests do not touch real services.

## Supported operations

- **Install:** monitoring-only by default, optionally remote power.
- **Upgrade and repair:** the trusted root-side backend reads the existing
  private installation UUID before applying, without asking the unprivileged
  wizard to read a protected file. It compares the stored identity after a
  running agent restarts and preserves enabled/active service intent.
  For an intentionally stopped agent, HTTP verification is skipped and
  identity preservation is explicitly **not_verified**, not guessed.
- **Finish terminal cleanup:** remove a leftover pending/ready stage after
  COMMITTED, ABORTED or ROLLED_BACK without installing again.

Uninstall and recovery after a sudden crash during an applied phase are
separate unfinished workflows. No privilege escalation, CLI, or Go wizard
execution is enabled here.

## Lock and lifecycle sequence

The controller acquires the **exact existing** manual lock file,
'/run/lock/linux-host-agent-install.lock', using exclusive flock.
The lock remains held throughout staging, snapshot, applying, systemd,
health verification, rollback and cleanup. A concurrent manual installer
blocks the wizard with a clear 'installation_busy' result, without
creating a journal or touching managed files.

1. Validate a fixed-schema install/upgrade/repair request, trusted
   system Python path, version and explicit features. The only supported
   listener port is **8765** until the service unit becomes configurable.
2. Record journal INSPECTED.
3. Stage all ten files from a manifest authenticated independently by
   the future root-owned launcher. Record STAGED.
4. Obtain the verified staged source while the stage receipt remains
   open. Read the existing UUID from root-protected state, only inside
   the backend; never echo or return it in public JSON. Generate the actual
   install_core plan, including preserved power and stopped/disabled
   service settings.
5. Snapshot managed files and previous unit states. Sync original files,
   backup manifest, snapshot and backup parent **before SNAPSHOTTED**.
6. Record APPLYING **before any managed mutation**. Durably write the
   small non-secret v2 ownership record **before** running getent/useradd:
   this permits validation of this transaction's empty first-install
   snapshot even if user creation fails. Then idempotently ensure the
   existing manual installer's 'linuxhost' account and apply the actual
   plan using the existing engine; sync managed directories.
   The service account is deliberately retained on rollback, matching
   the manual installer's existing behavior.
7. Record ACTIVATING and use the existing service behavior. The expected
   power-socket active and enabled states use the **same calculation**
   as install_core.activate(): when power is on, an enabled-but-stopped
   socket is enabled **and started** by enable --now. The gate must not
   falsely rollback that successful upgrade.
8. Record VERIFYING and require correct files, service state, and a
   passing PR #73 runtime check if the agent is meant to be running.
   A previously stopped agent remains stopped and is verified without
   making any HTTP request.
9. Record COMMITTED; retire the stage; clear the terminal journal.
   Only then release the manual lock.

Monitoring does not require power-control opt-in. The backend's WOL
option is **only a physical interface pin in the unit environment**.
It does not enable persistent WOL through configure-wol.sh, adjust
NetworkManager/systemd-udev, or change firewall/network settings.
The wizard must **not** offer a persistent-WOL setup operation through
this backend until that opt-in path exists.

## Legacy installation and manual CLI coordination

The legacy v1 linux-host-lan agent and the new computer-host-lan v2 agent
share managed paths. We selectively integrated the **compatibility guard
and recovery fixes from closed, unmerged PR #70** rather than reopening
the old PR wholesale. Both the backend and manual installer now refuse
a recognized v1, mixed or unrecognized installation **before installing**.
There is no automatic v1 migration. A bounded signature check looks at
the managed agent's declared protocol and the existing Avahi service,
never the private UUID or control key.

A small root-owned **non-secret v2 ownership marker** (fixed content `v2`)
is stored in a **0755 directory with a 0644 file**, so a normal-user
preflight or read-only wizard can recognize it. It never contains a UUID,
control key or user configuration. Reads reject group/other-writable paths
and report permission errors as controlled installer errors, not tracebacks.
The record survives uninstall and a failed fresh install, allowing a
legitimate v2 reinstall when only the private agent state remains. An orphan state directory without a proven v2 marker
does not get silently adopted: the manual installer alone has an explicit
expert --adopt-retained-state route, and can never use it to override
recognizable v1 files. Snapshot provenance and the v2-specific backup
validator avoid restoring an accidental v1 backup over v2.

The existing manual installer still holds its original OS flock. It now
also reads the wizard journal status **under that lock**, including on
--rollback, and refuses --install, --uninstall and --rollback unless
the journal and protected staging report 'none'. The shell front-end performs an early read-only
v1 and journal check before useradd. A wizard crash therefore cannot
be overwritten by a later sequential manual install, which would
otherwise invalidate the wizard's recovery snapshot.

The read-only JSON plan rejects v1/ambiguous hosts with its existing
prerequisite_missing error. The backend additionally distinguishes an
orphan-only retained state as `adoption_required` with fixed text directing
the user to the manual installer `--adopt-retained-state` **only after**
confirming the retained state is v2. The Go wizard is not yet connected
to this backend; dedicated migration UI/status remains an API/Go decoder
follow-up (issue #71).
Source-only parity tests use clean hosts and recognizable v2 fixtures.

## Errors and recovery behavior

Before APPLYING the controller has not modified managed files or services.
An ordinary error aborts and cleans the staged payload. Bad hashes,
invalid requests and snapshot failures never produce a partial install.

After APPLYING, caught failures (including verification errors) trigger
restore of the previous managed files and unit states. The controller
independently compares restored contents/modes to the backup and
checks service state before recording ROLLED_BACK. If verification fails,
the journal and stage are deliberately retained, and the user receives
'recovery_required' rather than a false successful rollback.

Once COMMITTED, cleanup errors return 'installed_cleanup_required':
the agent already passed verification. A later run can finish that
terminal cleanup, retaining identity and without reinstalling.

The new data-only staging helper can remove either a matching pending
or ready tree after a terminal journal outcome, validating every entry;
it does not execute or authorize any staged content.

## Important remaining gates for a working wizard

**No trusted privilege-handoff entry point exists yet.** A later
separately installed and authenticated root-owned launcher must pin its
own code and the exact payload manifest, use a trusted interpreter in
isolated mode (-I -B), trusted import paths, cleaned environment and
bounded request arguments. Never execute this module as root from an
untrusted user-writable checkout. The Go wizard remains separate.

**Sudden power loss after APPLYING remains unresolved.** The next
milestone must implement restart recovery for an abandoned applied-phase
journal, independently validate its protected snapshot, restore previous
managed files and service intent, and verify recovery before clearing
the transaction. Do not activate installation by default until this is
tested. Power loss while terminal cleanup is pending is already covered.

Real Linux systemd integration and Gentoo testing must be performed
after the privileged launcher and recovery engine are reviewed.

## Test strategy and CI efficiency

The test suite runs the **real file installer** in a temporary root with
the actual ten-file repository payload and a fixture manifest, but
never invokes systemd/sudo or changes the host. It covers:

- clean default install; explicit remote-power opt-in;
- account preflight only after APPLYING, including missing-user creation,
  existing-user preservation and failure-triggered rollback;
- upgrade and repair, preserving stopped and disabled service intent,
  with the root backend obtaining the current UUID and declining to
  claim verification for intentionally stopped agents;
- existing power socket enabled but stopped, including first-install
  power activation semantics: no false rollback;
- legacy v1 and ambiguous-layout refusal for both backend and manual
  commands, retained v2 ownership/reinstall and snapshot checks;
- manual installer refusal when the wizard journal is incomplete,
  including rollback under the shared lock;
- a genuine unprivileged user reading the v2 marker after uninstall
  (when the CI host can drop privileges), denied marker reads returning
  `InstallError`, and exact visibility under umask 077;
- fresh-install useradd failure rolls back and can be retried instead
  of blocking a subsequent wizard operation;
- agent crash leaving `installation-id` with a second hard link, without
  changing its UUID or aborting upgrade;
- a failed live health gate and verified restoration of previous bytes;
- refusal to claim successful rollback if service restoration fails;
- bad source hash, interrupted staging and snapshot failures;
- the common manual lock preventing concurrent wizard installation;
- a crash-equivalent terminal cleanup failure and later cleanup **without
  reinstalling**;
- running versus intentionally stopped service health rules;
- invalid requests and compatibility with the manual lock's 0644 mode.

This PR is intentionally one functional integration increment rather
than multiple minor hardening PRs. CI is source/fixture verification,
not proof of actual root launch or power-loss durability.
