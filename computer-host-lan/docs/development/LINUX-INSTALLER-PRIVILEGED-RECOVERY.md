# PR #77 — applied-phase crash recovery and fixed privileged request boundary

**Status:** Python backend and privilege-handoff contract with source/fixture
tests. This is **not** a deployed or production-enabled wizard. Neither
the live `linuxhost` agent, its UUID/key, WOL, systemd, SmartThings driver
nor any current installation is changed merely by merging this PR.

## Why combine these changes?

After #73–#76, the backend installs, verifies and rolls back when it *catches*
an exception, and safely completes terminal cleanup. Two practical pieces
were missing before the Go wizard can safely offer live installation:

1. Recover an actual interrupted `APPLYING`, `ACTIVATING` or `VERIFYING`
   journal after power loss or the installer being killed.
2. Provide a bounded **root-installed** request/response endpoint, so
   the ordinary-user wizard never runs a writable checkout as root.

Both belong in a single engineering review because the privileged command
must expose safe recovery **before** it can offer installation.

## 1. Restart recovery

`InstallerBackend.recover_interrupted()` uses the **existing common lock**
(`/run/lock/linux-host-agent-install.lock`) and acquires the durable journal
with `ProtectedJournal.resume_recovery()`, not `begin()`. It does not
silently perform an upgrade, re-pair a SmartThings device or rotate a key.

| Recorded phase | Recovery behavior |
| --- | --- |
| `INSPECTED`, `STAGED`, `SNAPSHOTTED` | No managed file write has started. Record `ABORTED`, remove the matching safe stage and clear the journal |
| `APPLYING`, `ACTIVATING`, `VERIFYING` | Locate **only** `snapshot_name` from the protected journal, validate the v2 snapshot, restore previous files and systemd intent, independently verify both, record `ROLLED_BACK`, then retire the stage and journal |
| `COMMITTED`, `ABORTED`, `ROLLED_BACK` | Complete interrupted stage/journal cleanup without reinstalling, restoring or restarting a verified installation |
| No valid protected journal, missing/unsafe backup, failed restoration | Refuse or return `recovery_required`; do not claim success or erase evidence |

This operation is **explicit**, never a side effect of opening the wizard or
pressing Install. A failed file or service restoration keeps the applied
journal; the user can retry recovery after correcting the underlying issue.

The snapshot lookup is constrained to
`/var/backups/linux-host-agent/<validated snapshot_name>` under
the already protected backup namespace. It validates the existing
`installer_protocol=v2` backup structure **before writing any managed file**.
Only the matching protected applied-phase journal may use the narrowly
scoped `journal_owned_fresh_install=True` backup-validation exception.

### Important first-install crash window

The first installation writes the persistent, non-secret v2 ownership marker
*after* recording `APPLYING`. Power loss can therefore occur before that
marker exists. For the **matched protected journal only**, the backup
validator accepts an empty-agent snapshot with explicit v2 provenance;
recovery then writes the non-secret marker and restores the verified
previous state. Normal/manual `--rollback` still requires the usual
owner-marker proof and cannot adopt legacy v1 snapshots.

The service account created during a failed install is retained as in the
manual installer; the agent's private UUID and power key are not restored
from or copied into snapshots.

## 2. Privileged launcher: installed-only boundary

`scripts/installer_root.py` is a **fixed-location root helper**, not
a self-elevating script. It will **refuse execution from a source checkout**,
even with sudo. The future authenticated package must install it alongside
`installer_transaction.py`, `install_core.py`, `payload_staging.py`,
`transaction_journal.py` and `runtime_verify.py` under:

`/usr/libexec/computer-host-lan/`

The same trusted directory must contain `trusted-payload.json`, generated
during packaging and installed as root-owned data. Before importing
project code or accepting the request, the root helper requires:

- real root EUID and its *exact* installed script path;
- root-owned, non-group/world-writable parents and each importable helper,
  all opened without following symlinks;
- an isolated Python invocation with **`-I -S -B`**;
- a root-owned, bounded manifest containing **exactly ten SHA-256 digests**
  and the version matching the reviewed payload;
- only after validation, a cleaned environment and explicitly trusted
  module path.

The helper is **not an authenticity mechanism** for itself. The release
package/installer must authenticate the helper, its dependencies, and
trusted manifest **before** putting them in the fixed root directory.
Do not put the manifest beside an untrusted download and assume its
checksums establish provenance. The installer must also sanitize the
invoker's environment *before* the Python process starts (the Python
process cannot undo what the dynamic linker already loaded).

### Versioned request/response contract

The future Go wizard passes a bounded JSON object on standard input after
a user-visible confirmation and a separate successful sudo/polkit
authorization. It must restore terminal canonical mode before the password
prompt; `sudo -n` should be used for noninteractive operation.

Command (after trusted package installation, **not** from the repository):

```sh
/usr/bin/python3 -I -S -B /usr/libexec/computer-host-lan/installer_root.py --request-stdin
```

Example request (source is only an **untrusted bytes source** that must pass
the separately installed, root-owned SHA-256 manifest):

```json
{
  "schema_version": 1,
  "action": "install",
  "source": "/home/user/Downloads/computer-host-lan",
  "power": "preserve",
  "wol_interface": null
}
```

`action` is `status`, `recover`, `install`, `upgrade` or `repair`.
For `status` and `recover`, **only** `schema_version` and `action` are
allowed. No arbitrary Python interpreter, destination path, systemctl
argument, raw shell, UUID, token, or port is accepted from the wizard.
Only the source directory of the untrusted ten-file payload is caller
controlled, and every byte is authenticated in protected staging.

The response is exactly one machine-readable JSON line with schema v1,
stable status/error codes and `secrets_included:false`. It never contains
a journal transaction ID, backup path, UUID, control token, full request,
or traceback. Status reports `privileged_transaction_state`; `recover`
reports only `aborted`, `rolled_back`, `cleaned`, or `nothing_to_recover`.

`scripts/generate_trusted_payload.py` produces a ten-file checksum/agent
version manifest during packaging. This build helper is **not** itself a
release signature; only a manifest installed with authenticated root-owned
code can serve as runtime expected hashes.

## 3. CI tests / acceptance

The Python fixture suite covers process-exit simulation at
`STAGED`, `SNAPSHOTTED`, `APPLYING`, `ACTIVATING` and `VERIFYING`;
restoration of previous *actual managed file bytes*, service intent,
terminal stage cleanup, and refusal to erase an applied journal on an
invalid backup or failed restore. A first-install crash *before owner
marker publication* is tested, including ability to retry installation.
Regression tests verify the root boundary's strict JSON schema, duplicate
keys, invalid paths, unrecognized options, source checkout refusal,
manifest allowlist/version matching and absence of private data in
responses. There is no sudo, real systemd invocation or live agent write.

**Release acceptance still required:**

1. Finish independently authenticating and installing the root helper plus
   trusted manifest from a version-pinned release (no execute-from-/tmp).
2. Connect the Go wizard's explicit Review/authorization/Execute steps to
   this stdin/JSON contract, keeping TUI terminal ownership correct.
   **The Go wizard lives in separate draft PRs #67/#72, not on `main`.**
   Do not copy that experimental UI wholesale into this backend PR.
3. Review the implementation and test both normal and crash/recovery
   workflows on actual systemd/Gentoo with reversible snapshots.
4. Only then promote it as the supported Linux installer.

This PR makes the backend recoverable and defines the fixed privileged
endpoint, but **does not yet deploy or invoke it on `hydra`**. It does not
enable an interactive or elevated installer automatically.
