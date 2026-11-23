# Linux wizard protected transaction journal — foundation

**Status:** isolated foundation, NOT integrated into the production installer.  
**Scope:** `scripts/transaction_journal.py` and rootless fixture tests only.  
**Production behavior:** unchanged. No service, account, key, identity, port, firewall, WOL or agent file is touched by this PR.

## Why this exists

The established `install_core.py` can roll back after ordinary Python exceptions, but an
interruption after a partial file write/activation needs a durable recovery marker.
PR #73 added a bounded, read-only runtime verifier; it **must not yet** be used
as a commit/rollback gate while no crash-safe transaction protocol exists.

This module provides the narrowly scoped state-machine *building block*. It
does not execute the installer, prove snapshot integrity, perform recovery,
supply a privilege boundary, or modify the current `install-agent.sh`.

## Private storage and allowed state

Future **trusted root code only** will use
`/var/backups/linux-host-agent/wizard-transactions/journal.json`, located
separately from the agent-owned state at `/var/lib/linux-host-agent`.
Its lock and journal are private files (0600) inside root-owned private
directories (0700). Parent directories are opened through fixed, no-follow
directory file descriptors and checked for trusted ownership and unsafe
write permissions. Journal reads reject symlinks, hardlinks, wrong owner,
non-regular files, excess size, malformed/duplicate JSON fields and
unknown schema or values.

The journal contains only:

- `schema: 1`
- allowlisted `operation: install | upgrade | repair | uninstall`
- ordered `phase`
- an optional, validated snapshot **basename** (never an arbitrary pathname)

No key, UUID, host address, hub details, arbitrary input, environment or
credential is recorded. Snapshot **ownership, contents and restoration
validity must be checked separately** in a future recovery implementation.

```text
INSPECTED -> STAGED -> SNAPSHOTTED -> APPLYING
          -> ACTIVATING -> VERIFYING -> COMMITTED
```

Writes create a private, uniquely named temporary file, write and fsync
its contents, atomically replace `journal.json` and fsync the containing
directory. Explicitly ordered transitions are guarded by a private advisory
lock and expected-phase check. A crash leaving a temporary journal file
blocks new transactions rather than silently discarding uncertain state.
Only an explicitly COMMITTED journal may be cleared; unfinished state
must remain available for a future manual/recovery action.

The *future trusted root status endpoint* can call `public_status()` to
return only a fixed, redacted JSON shape:

```json
{"schema_version":1,"operation":"protected_status","mode":"privileged_read_only","privileged_transaction_state":"none","secrets_included":false}
```

`privileged_transaction_state` is one of `none`, `incomplete` or
`recovery_required`. A leftover temporary file forces
`recovery_required`. Malformed or unsafe journal paths **raise an error**
rather than being interpreted as an empty/healthy transaction. These
errors must be mapped to a fixed code by the future privileged controller,
without exposing exception details.

## Important security boundaries

**Do not use `sudo python scripts/transaction_journal.py` from a working
tree, and do not expose the fixture `root` / `owner_uid` arguments through
a public interface.** The file deliberately has no privileged CLI. The
real privileged launcher, trusted root-owned code and verified staging
must be designed and reviewed separately. A checksum verified by code
loaded from an attacker-writable directory is not sufficient.

The existing unprivileged `installer-api.sh inspect` intentionally keeps
`privileged_transaction_state: "unknown"`. This journal's redacted status
is *not* spliced into that unprivileged API. A future privileged helper
must avoid rendering the raw journal or snapshot reference.

All filesystem tests use a temporary root with injected fixture ownership;
there is no need for sudo and **no live host modification**. The module
never writes directly under `/var` in tests.

## Remaining milestones before an installing wizard

1. Root-trusted, verified payload staging and an explicit, controlled
   elevation handoff; do not execute user-writable source as root.
2. Integrate journal creation and phase transitions into the existing
   installation engine under the **same installation lock** used by the
   established CLI. Prevent overlap with manual install/rollback.
3. Validate existing backup manifests, snapshot directories, service
   intent, persistent ID and retained key with no-follow/ownership rules.
   Implement safe restart recovery and clear failure reporting.
4. Use the PR #73 verifier for actually-running services with expected
   version, identity and power state supplied **in memory** by trusted
   code; intentionally stopped services require separate verification.
5. Review Go UX integration and post-install onboarding only after the
   privileged transaction is safe and tested on disposable hosts.

**Do not merge a PR that claims the wizard can perform real installs
merely because the journal module exists.** Container CI alone does not
prove power-loss durability, distribution permissions or physical-device
acceptance.
