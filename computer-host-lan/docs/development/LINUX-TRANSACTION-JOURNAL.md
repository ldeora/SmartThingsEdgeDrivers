# Linux wizard protected transaction journal — foundation

**Status:** isolated, review-only foundation; **NOT** an installing wizard.  
**Scope:** `scripts/transaction_journal.py`, fixture tests and this design note.  
**Production behavior:** unchanged; no systemd, agent, service, power, credentials,
firewall, WOL, SmartThings pairing or release changes.

## Objective and state machine

PR #73 provides bounded, unprivileged runtime verification, but the current
`install_core.py` only rolls back when a Python exception is caught.
The wizard needs durable phase tracking and explicit recovery ownership
before runtime health can become a commit/rollback gate.

The protected journal is reserved for **trusted root-side code**, separately
from `/var/lib/linux-host-agent` (persistent UUID and control key).
It is not connected to `install-agent.sh`, `installer-api.sh` or
the draft Go wizard. It has **no sudo CLI**.

```text
INSPECTED -> STAGED -> SNAPSHOTTED -> APPLYING
          -> ACTIVATING -> VERIFYING -> COMMITTED

INSPECTED / STAGED / SNAPSHOTTED -> ABORTED
APPLYING / ACTIVATING / VERIFYING -> ROLLED_BACK
```

- `ABORTED` means the trusted controller confirmed **no managed
  installation mutation happened yet**. It is never allowed from an
  applied phase.
- `ROLLED_BACK` is permitted only after a trusted callback attests to
  successful rollback of the protected snapshot, installed files, identity
  and service state. This module **does not implement rollback or snapshot
  validation**; the callback is an integration contract, not proof by itself.
  Using a hard-coded `lambda _: True` in production would be unsafe.
- `COMMITTED`, `ABORTED`, and `ROLLED_BACK` are terminal.
  An abandoned terminal journal is considered complete and can be
  automatically reaped by `begin()` while holding the lock, provided
  no uncertain staging files remain. `finish_terminal()` explicitly
  finishes cleanup if a process died before it was cleared.
- A crash before `APPLYING` can be resolved by `resume_recovery()` +
  `abort()`; a crash after `APPLYING` requires an actual independently
  validated rollback before `mark_rolled_back()` and `clear_finished()`.
  Neither path silently erases a live or unresolved transaction.

## Exclusive lifetime lock and concurrency

`begin(operation)` returns a `TransactionHandle` holding a private
non-blocking `flock` and directory fd for **the entire transaction**.
The caller must keep the handle in a `with` block while applying,
activating and verifying. `advance`, `abort`, `mark_rolled_back`,
and `clear_finished` are methods on that exclusive handle. An
independent caller cannot start or resume while it remains open.
The journal has a random, private 128-bit `transaction_id` and
the handle revalidates ownership and expected phase on each change.

After a crash, the OS releases the lock and
`resume_recovery()` can exclusively acquire a new handle for the
remaining journal. The lock fd is created once with no-follow
and private permissions. Status opens it **read-only, without O_CREAT**
and attempts a **non-blocking shared lock (`LOCK_SH | LOCK_NB`)**.
Concurrent status calls can hold shared locks simultaneously and cannot
misclassify another status reader as an active installation. A writer's
exclusive lock prevents shared inspection, yielding `in_progress`
without reading a potentially changing journal.

Transaction owners obtain an **exclusive** lock (`LOCK_EX | LOCK_NB`).
To tolerate a brief shared status probe, owner acquisition retries for a
**hard 1.25-second monotonic deadline**, sleeping at most 25 ms between
attempts. This still bounds waiting when another actual transaction owns
the exclusive lock. Status never waits and never retries.

**Fork safety:** Do not fork while holding `TransactionHandle`. A child
inherits its lock file descriptor and could keep the parent transaction
apparently `in_progress` after the parent exits. If a fork is unavoidable,
close the *inherited handle* immediately in the child; never call
`LOCK_UN` on that shared open-file description because it can unlock
the parent's lock prematurely. Ordinary child execution and root privilege
handoff must be designed to avoid inheriting a live transaction handle.

**Important unfinished integration:** this private lock is not yet
the same as the existing manual CLI install lock,
`/run/lock/linux-host-agent-install.lock`. Before any privileged wizard
execution can be enabled, the future controller MUST coordinate both paths
under a shared install lock and preserve existing manual install/rollback
semantics. A private journal lock alone does not prevent manual CLI
concurrent mutation. This PR makes no claim otherwise.

## File safety and redaction

Root-side production storage will be:
`/var/backups/linux-host-agent/wizard-transactions/journal.json`.

The journal and lock are 0600; private application directories are 0700.
Existing `/var` and `/var/backups` may be normal root-owned 0755
directories and their permissions are never normalized. If absent, these
general-purpose parents are created as **exactly 0755**, while new
application-specific directories are **exactly 0700**. After a new directory
is opened without following links and its owner is verified, `fchmod`
sets the intended mode independently of the process umask, and `fsync`
persists it. Existing directories are checked but never chmod'd.

Fixed-component no-follow dirfd walking rejects symlinks and unexpected
owners/modes. Regular journal and lock files must have one hardlink and
strict 0600 permissions. Reads are bounded to 2 KiB, reject malformed or
duplicate-key JSON, unknown fields and versions, invalid phases,
invalid snapshot basenames and inconsistent snapshot/phase combinations.
The compact journal stores only `schema`, random
`transaction_id`, operation, phase and optional constrained snapshot
**basename**. It never contains credentials, UUID, hub addresses, logs,
arbitrary paths or host network details.

Writes validate all fields, create a unique private temp file, write and
fsync it, atomically rename over the journal, then fsync the directory.
A failed write leaves any unrenamed staging file as a recovery marker.
Only a trusted, lock-owning controller may reconcile such markers after
independently verifying the installed state. For an orphan created during
the *very first* journal write, `reconcile_orphaned_staging()` demands a
trusted no-mutation verifier before deleting validated temp files.
For an interrupted later phase update, a trusted verification callback is
required before abort or rollback completion; `clear_finished()`
performs strictly checked temp cleanup. Suspicious staging entries are
not automatically deleted.

## Read-only status contract

The future trusted root-side status operation may call `public_status()`
to return one fixed object:

```json
{"schema_version":1,"operation":"protected_status","mode":"privileged_read_only","privileged_transaction_state":"none","secrets_included":false}
```

| State | Meaning |
| --- | --- |
| `none` | No journal, or a completed terminal journal with no uncertain markers |
| `in_progress` | Lifetime lock held by an active transaction/recovery owner |
| `incomplete` | Unlocked `INSPECTED`, `STAGED`, or `SNAPSHOTTED` journal; explicit abort/resume needed |
| `recovery_required` | Unlocked `APPLYING`, `ACTIVATING`, `VERIFYING`, uncertain temp write, or inconsistent missing-lock condition |

Unsafe paths, invalid JSON, unreadable files and unsupported schema **raise a
static error**, never a reassuring `none`. The future privilege bridge
must map exceptions to fixed redacted error codes, not echo their contents.

The unprivileged `installer-api.sh inspect` still returns
`privileged_transaction_state: "unknown"`. No unprivileged operation
reads protected files or transaction IDs. Status is not proof that a
snapshot has been restored or that the SmartThings hub is reachable.

## Validating this review-only milestone

`tests/test_transaction_journal.py` operates under temporary
non-root fixture directories; it does not call systemd/sudo or modify
`hydra`. Coverage includes all phase transitions, ABORTED/ROLLED_BACK
guards, COMMITTED cleanup, malicious journal input, symlinks, hardlinks,
permissions, private redaction, failed write temp markers, concurrent
shared status readers, a short exclusive acquisition blocked by a status
reader, an exclusive-owner contention timeout, strict new-directory modes
under umask 077, preservation of pre-existing parent modes, a live
subprocess holding the lifetime lock, and subprocess `os._exit()` crashes at
**every** ordered phase followed by the permitted recovery transition.

### Remaining requirements before actual privileged installation

1. **Trusted root-owned staging and authorization:** no root execution of
   code from a user-writable source tree. Secure verified payload manifest
   and narrow elevation protocol are still missing.
2. **Shared installer exclusion:** coordinate with the established
   `/run/lock/linux-host-agent-install.lock` and existing shell installer.
3. **Actual snapshot validation/recovery:** verify snapshot metadata,
   ownership, fsync durability, app-owned managed file integrity,
   service enabled/stopped intent and preserved private identity; implement
   restore before invoking rollback completion callbacks.
4. **Trusted runtime health gate:** call PR #73's verifier only after safe
   activation, compare expected agent version/UUID/power state in memory,
   and distinguish intentionally stopped services from running ones.
5. **Go wizard and onboarding:** only after the privileged engine and
   crash-injection tests are reviewed. Keep the Go TUI out of the root process.

A successful source-only CI run is **not proof** of power-loss durability,
real systemd integration, WOL, firewall behavior or SmartThings pairing.
