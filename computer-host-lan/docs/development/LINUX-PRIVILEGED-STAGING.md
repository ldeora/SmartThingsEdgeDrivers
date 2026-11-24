# Linux installer PR #75 — protected, transaction-bound payload staging

> **Historical design note:** Describes the implementation at its original milestone. For current behavior, see [Linux installer architecture](LINUX-INSTALLER-ARCHITECTURE.md).

**Status:** isolated DATA-ONLY milestone, not a working privileged installer.  
**Production behavior:** unchanged. No sudo/polkit, installed agent/service,
systemd, persistent UUID, token, firewall, networking, WOL or hub interaction.

## Trust boundary

PR #73 adds bounded runtime verification; PR #74 adds a durable private
transaction journal. The Linux installer still must not execute
`install_core.py` as root from a user-writable source checkout. This PR
provides the narrow, non-executing primitive for moving a verified payload
into a protected installer namespace with guarded cleanup.

`scripts/payload_staging.py` is a library without a CLI, subprocess, shell,
service manager or elevation path. It is **never appropriate to run it as root
from an ordinary checkout**. It requires a **live exclusive
`TransactionHandle`** from PR #74, bound to the *same protected root and
owner* as the staging directory.

### Chosen installer namespace

- **Installer staging and its lock:**
  `/var/lib/computer-host-installer/staging` (root-owned 0700)
- **Installer transaction journal and recovery snapshots:**
  `/var/backups/linux-host-agent/wizard-transactions`
- **Existing persistent agent identity/key:**
  `/var/lib/linux-host-agent` (never staged, copied or cleared here)

These paths are now the intentional installer namespaces for future
uninstall/repair/recovery implementation. The installer state and private
agent runtime state remain separate. Nothing in this PR creates a service or
user, or changes current installation or uninstall behavior.

## Fixed payload, integrity, and source policy

The allowlist contains exactly ten files: the two agent Python files, the
three systemd units, optional power drop-in, Avahi template, and
`install_core.py`, `runtime_verify.py`, `transaction_journal.py`.
The caller supplies expected lowercase SHA-256 hashes for **exactly**
those names. Individual files are limited to 1 MiB and the total payload
to 4 MiB; content is checked in memory **before** staging directories
are created.

Source folders/files are opened with no-follow dirfds. Symlinks, FIFOs,
special files, missing files and size/digest mismatches fail closed.
**Source hardlinks are intentionally allowed:** because the bytes are
authenticated and kept in bounded memory before staging, another link
does not weaken source integrity. The **staged** files retain strict
single-link mode 0600 and trusted ownership. Files copied from the source
cannot be swapped after verification: only the verified bytes are written.

Destination traversal is fixed, no-follow, and checks owner/mode. Shared
parents `/var` and `/var/lib` are accepted with ordinary root-owned
permissions; newly created ones get exactly 0755, independently of umask.
Installer-private directories get exactly 0700, existing directory modes
are not normalized. Each output file is created exclusively, written,
fsynced and rehashed; directories are synced before and after rename
from `pending-<transaction-id>` to `ready-<transaction-id>`.

## The journal and staging binding

**Stage ID = the journal's existing random 128-bit transaction ID.** This
is an intentional schema-compatible binding: PR #74 already durably
records `transaction_id` before `STAGED`. The stage does **not** invent
a second independent ID, and the journal schema need not change merely
to name a staged payload. Its filesystem name is deterministically
`ready-<transaction-id>`, never selected by an untrusted caller.

The journal handle exposes the validated ID only to protected code.
`stage_payload(source, trusted_hashes, transaction)` requires an active
journal at phase `INSPECTED`, and verifies the transaction owner/root.
Staging holds its own **exclusive lifetime lock** and directory handles
until its `StagedPayload` receipt is explicitly closed or retired. The
same active journal handle must remain alive in the caller.

The receipt provides:
- `stage_id` — the same private ID as the held journal transaction
- `directory_fd` — `CLOEXEC` open handle to the verified ready folder
- `verify(trusted_hashes)` — compare stage path's `st_dev/st_ino` to
  the held handle, require strict file tree/ownership/mode/link checks,
  and rehash **every** file against the trusted caller's hashes
- `verified_source_path(trusted_hashes)` — an absolute source path only
  after those identity and content checks **and** after the journal has
  durably entered `STAGED` (or a later nonterminal phase). It refuses
  `INSPECTED`, `ABORTED`, `ROLLED_BACK` and `COMMITTED` so a crashed
  or completed stage cannot be treated as executable input

The receipt is process-bound. An inherited receipt in a forked child
cannot retire or use the parent's stage. Do not fork while holding it:
the child can inherit lock references until it exits. Never call
`LOCK_UN` on a shared inherited lock description.

**A directory named `ready-*` is only verified data, never executable
authorization.** After a crash, a trusted caller must reacquire the
journal transaction (or `resume_finished_cleanup()` for terminal state),
independently authenticate the same payload manifest, and call
`recover_ready(manifest, transaction)` to re-open and recheck the
specific folder tied to that transaction. No stage from a different
transaction or with unexpected entries is accepted. The result is still
not authorization to execute anything.

### Cleanup: no manual root deletion needed for a valid staged tree

- `discard_pending(transaction)`: under an exclusive stage lock, delete
  **only** `pending-<this journal transaction ID>`. The contents may
  be partial but must consist entirely of the expected allowlisted
  directory/file names with correct root ownership/modes and no links
  or special files. It refuses extra entries, symlinks, hardlinked files,
  unsafe owners or a stage belonging to another transaction. It is only
  permitted while the journal is `INSPECTED`, `STAGED` or `ABORTED`.
- `retire_ready(receipt, trusted_hashes)`: the original receipt's
  process must still own the exclusive stage lock and a **terminal**
  journal (`COMMITTED`, `ABORTED`, `ROLLED_BACK`). It checks the
  visible folder's inode/device against the receipt and verifies the
  full payload again before unlinking any files using directory fds.
- `finish_retirement(transaction)`: a dedicated recovery path after a
  crash in the middle of deleting an already terminal stage. It is
  available only with the matching **terminal journal** and permits an
  incomplete allowlisted file tree, never execution or source reuse.
  It rejects unsafe or unexpected files. Unlike `recover_ready`,
  this operation is for deletion **only**. Both `discard_pending`
  and `finish_retirement` can be replayed after their final `rmdir`
  but before the containing-directory `fsync`, making successful
  cleanup idempotent. Future root-side controller must complete it
  before clearing terminal journal state.

**Required install/upgrade ordering (functionality invariant):**

1. Hold the **journal transaction handle** throughout the operation.
2. `stage_payload()` produces `ready-<txid>`; durably advance the journal
   from `INSPECTED` to `STAGED`.
3. Call `verified_source_path(trusted_hashes)`, then invoke the existing
   installation engine **immediately while the stage receipt is still open**
   and its exclusive lock keeps the protected payload stable.
   The future trusted launcher must also hold the shared manual-install
   exclusion lock; **this PR still does not execute the engine**.
4. After activation/verification, durably record `COMMITTED` (or perform
   verified rollback and record `ROLLED_BACK`; pre-apply cancellation may
   record `ABORTED`).
5. **Retire the ready stage, or discard its pending stage, before calling
   `clear_finished()`.** Only then may the transaction journal be removed.

An interruption after commit but before stage retirement is a **cleanup
task**, not a failed installation. When the next wizard run calls `begin()`,
it must **not** silently discard the terminal journal if a stage remains.
The journal now refuses `begin()`, `clear_finished()` and
`finish_terminal()` while any staged payload exists. Privileged status
reports `recovery_required` for an unlocked terminal journal with a
remaining stage. The controller can call `resume_finished_cleanup()`,
`finish_retirement()`, then `clear_finished()`, and only afterward
begin an upgrade or repair. An interrupted `pending-*` stage is cleared
via `discard_pending()` while the matching journal still exists.

This intentionally keeps the existing two fixed private directories instead
of moving or merging them. The guard is a small functional correction in
PR #75, and avoids a second payload-tree implementation inside the journal.

An interruption after staging but before advancing to `STAGED` is also
recoverable: `resume_recovery()` + `recover_ready()` under journal
`INSPECTED`, then `advance('INSPECTED', 'STAGED')`, then
`verified_source_path()`. Neither the stage name nor the receipt alone
authorizes consuming the files.

Every cleanup operation holds the staging lock, validates the fixed
allowlist and types, unlinks files via parent directory descriptors, and
fsyncs the containing directory. No recursive walk outside the fixed
payload structure is permitted. A suspicious root-owned tree is an
explicit stop-and-diagnose condition; never erase it indiscriminately.
Missing stage files or unknown crash semantics must be handled by the
future recovery controller rather than presented as a successful install.

## Required future privileged launcher: separate trust contract

**No elevated code or execution is introduced by this PR.** The caller's
`trusted_hashes` are NOT intrinsically trustworthy; a downloaded manifest
beside a downloaded archive can be replaced together with the payload.

A root-owned launcher added later must:

1. Be independently authenticated/distributed and pinned as a trusted
   executable before user authorization. Never elevate a script, Go binary
   or Python entrypoint from a user-writable checkout or temp directory.
2. Use a **fixed trusted system Python interpreter**, launching it with
   `-I -B`, a controlled `PATH`, cleaned environment, deterministic
   arguments and a root-owned working directory. Do not inherit
   `PYTHONPATH`, `PYTHONHOME`, `LD_PRELOAD` or untrusted search paths.
3. Use only separately authenticated, version-matched SHA-256 hashes.
   Protect the launcher's own code and any importable helpers: staged
   files remain 0600, private, never imported through an untrusted path.
4. Pause the unprivileged TUI before a password prompt. Use a narrowly
   versioned request with no arbitrary root paths, shell fragments,
   Python interpreters, service names or executable arguments.
5. Bind the active journal, staged receipt, exact trusted manifest and
   request to **one** transaction. Reverify ready inode/device and
   every file immediately before invoking the existing engine, and
   preserve stage privacy through completion/recovery.
6. Share the existing manual installer exclusion lock at
   `/run/lock/linux-host-agent-install.lock`. Keep journal and stage
   locks under a documented global lock order to avoid deadlock.
7. Perform actual snapshot validation/rollback, preserve persistent
   key/UUID and existing stopped/disabled service state, and run PR #73
   runtime verification before recording `COMMITTED`.
8. Stage cleanup must complete before clearing the terminal journal;
   the journal now enforces this and preserves the transaction ID when a
   `ready-*` or `pending-*` stage remains after a crash.
   Recovery must resolve that stage before starting another operation.
9. Publisher provenance/signature verification is a **separate**
   prerequisite from content hash matching.

A verified `ready` folder alone never satisfies these requirements.

## Validation

`tests/test_payload_staging.py` uses disposable non-root filesystem
fixtures; no user service, agent process or system paths are modified.
Tests cover exact source digest/allowlist, untrusted source mutation,
symlinks, authenticated source hardlinks, hardlink refusal on staged
outputs, FIFO/special file size checks, exact modes under umask,
exclusive staging lock, pending marker failures, guarded pending
cleanup (including refusal of symlinked contents), complete
stage→retire→stage-again, full receipt re-verification, inode-swap
detection, crash reopen by journal identity, terminal cleanup after
interruption, refusal of premature journal cleanup, committed-crash
recovery before a later upgrade, recovery between staging and STAGED,
and a forked child's inability to retire the parent stage.

CI on Debian/Ubuntu/Fedora and Python 3.10–3.14 remains a
source-level safety check; it does not prove hardware power-loss
durability, privileged runtime behavior or SmartThings pairing.
