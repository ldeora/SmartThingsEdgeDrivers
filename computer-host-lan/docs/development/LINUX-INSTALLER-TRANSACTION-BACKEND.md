# Linux installer PR #76 — Transaction backend and shared installation lock

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
- **Upgrade and repair:** require independently obtained expected device
  UUID and preserve enabled/active service intent.
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
   system Python path, version, expected identity and explicit features.
2. Record journal INSPECTED.
3. Stage all ten files from a manifest authenticated independently by
   the future root-owned launcher. Record STAGED.
4. Obtain the verified staged source while the stage receipt remains
   open. Generate the actual install_core plan, including preserved power
   and stopped/disabled service settings.
5. Snapshot managed files and previous unit states. Sync original files,
   backup manifest, snapshot and backup parent **before SNAPSHOTTED**.
6. Record APPLYING **before any managed mutation**. Apply changes using
   the existing installation engine and sync managed directories.
7. Record ACTIVATING and use the existing service behavior.
8. Record VERIFYING and require correct files, service state, and a
   passing PR #73 runtime check if the agent is meant to be running.
   A previously stopped agent remains stopped and is verified without
   making any HTTP request.
9. Record COMMITTED; retire the stage; clear the terminal journal.
   Only then release the manual lock.

Monitoring does not require power-control opt-in. Merely choosing a WOL
interface does not change the host's persistent WOL or network settings.

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
- upgrade and repair, preserving stopped and disabled service intent;
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
