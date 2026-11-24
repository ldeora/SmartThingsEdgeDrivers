# PR #77 — applied-phase crash recovery and fixed privileged request boundary

> **Historical design note:** Describes the implementation at its original milestone. For current behavior, see [Linux installer architecture](LINUX-INSTALLER-ARCHITECTURE.md).

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

## 2. Privileged launcher: installed-only boundary and one-time bootstrap

`scripts/installer_root.py` is a **fixed-location root helper**, not
a self-elevating script. It will **refuse execution from a source checkout**,
even with sudo. A *downloaded, checksum-verified Go wizard* is the explicitly
authorized bootstrap: when run once with `sudo` in a narrowly scoped
bootstrap mode, it installs its own embedded **version-matched** helper
files and manifest as root-owned data. There is **no requirement for a native
RPM/DEB package** or a preexisting trusted launcher on first install.

The installed helper set includes `installer-entry.sh` and
`installer_root.py`, alongside `installer_transaction.py`,
`install_core.py`, `payload_staging.py`,
`transaction_journal.py` and `runtime_verify.py` under:

`/usr/libexec/computer-host-lan/`

The same trusted directory must contain `trusted-payload.json`, generated
during packaging and installed as root-owned data. Before importing
project code or accepting the request, the root helper requires:

- real root EUID and its *exact* installed script path;
- root-owned, non-group/world-writable parents and each importable helper,
  all opened without following symlinks;
- a root-owned `installer-entry.sh` that selects a compatible system
  Python with the exact same candidate order as `python-selector.sh`:
  `python3`, then `python3.14`, `python3.13`, `python3.12`,
  `python3.11`, `python3.10`. It uses a controlled system-only PATH,
  tests `sys.version_info >= (3, 10)` and launches the chosen interpreter
  with `-I -S -B`. `installer_root.py` independently refuses versions
  below 3.10 before loading the manifest or executing any request;
- a root-owned, bounded manifest containing **exactly ten SHA-256 digests**
  and the version matching the reviewed payload;
- only after validation, a cleaned environment and explicitly trusted
  module path.

The installed helper is **not an authenticity mechanism** for itself.
The user trusts the *downloaded Go installer binary* at the same explicit
privilege boundary as today's `sudo ./install-agent.sh` and an elevated
unsigned Windows Setup executable. The published release checksum must be
checked against an **independent trusted release reference** before
authorizing `sudo`; a hash shipped beside the same untrusted download
does not authenticate its publisher. No automatic silent elevation.

The Go bootstrap must clean the environment (especially `LD_*` and
`PYTHONPATH`) **before launching any root shell or Python process**.
The installed entry script then selects a compatible interpreter; merely
clearing environment variables inside Python is too late for its loader.
An unsupported system default is never written into `ExecStart`.
On RHEL 9 and openSUSE Leap 15.6, where `/usr/bin/python3` can be below
3.10, the selector must choose an installed `python3.11`, `python3.12`,
etc. If no compatible interpreter is installed, refuse **before staging
or modifying any managed installation files**, and show installation
guidance; do not change the system's default `python3` symlink.

### Concrete Go bootstrap and upgrade rule (decision for later UI work)

The Go wizard remains a normal-user app for Welcome, discovery, review and
read-only planning. At the confirmed installation step, it must restore
normal terminal mode before prompting for `sudo`, then explicitly run
**the same downloaded, version-verified Go binary** in a narrowly defined
privileged *bootstrap-only* mode. This is the single initial
`sudo`-authorized execution of downloaded code; it is an intentional
trust decision rather than an impossible promise to have zero elevated
downloaded code. That mode must not render a TUI or accept arbitrary
commands, shell scripts, Python paths or destinations.

The authorized Go bootstrap must:

1. Verify its embedded trusted helper set and the version-matched SHA-256
   payload manifest before writing. Use only the fixed
   `/usr/libexec/computer-host-lan` destination, no arbitrary paths.
2. Acquire the existing Linux installation lock and inspect the protected
   transaction state **before replacing an older launcher**. If the old
   launcher has an interrupted transaction, recover it with the matching
   **old** helper/manifest first (after explicit user confirmation), or
   refuse the upgrade. Never swap helper versions mid-transaction.
3. Create a private, root-owned temporary install location in the same
   trusted parent, write/verify/fsync the embedded files and manifest,
   then activate the complete new helper set. Preserve a validated previous
   set and restore it if activation fails; an interrupted replacement must
   be recoverable on the next bootstrap attempt. Do not leave half-updated
   Python helpers with an older manifest.
4. The first install has no previous set: install the helper and manifest
   before invoking it. On **every later installer upgrade**, install the
   **new version of the entire helper and manifest** before asking it to
   stage or apply the new agent payload. Otherwise the old trusted hashes
   would reject legitimate new release files.
5. After activation, invoke the installed `installer-entry.sh` with the
   bounded JSON request, under a clean environment. Treat an authorization
   failure, missing Python >=3.10 or failed helper update as **no agent
   change**. In noninteractive mode use `sudo -n` and never block waiting
   for a password prompt.

The design for atomic folder activation/recovery and a safely version-pinned
embedded Go bootstrap is part of the **next Go integration PR**, not
implemented by this Python-only PR #77. The existing prototype Go wizard
branches #67/#72 are still draft. Thus the entry script/contract can be
tested now without claiming a packaged or executable end-user installer.

### Versioned request/response contract

The future Go wizard passes a bounded JSON object on standard input after
a user-visible confirmation and a separate successful sudo/polkit
authorization. It must restore terminal canonical mode before the password
prompt; `sudo -n` should be used for noninteractive operation.

Command (after the approved Go bootstrap has installed the complete
root-owned helper set, **not** from the repository):

```sh
/bin/sh /usr/libexec/computer-host-lan/installer-entry.sh --request-stdin
```

The entry script selects and runs the compatible system Python itself, so
the wizard never hardcodes `/usr/bin/python3` into the agent service.

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

`action` in **schema v1** is `status`, `recover`, `install`,
`upgrade` or `repair`. For `status` and `recover`, **only**
`schema_version` and `action` are allowed. No arbitrary Python interpreter, destination path, systemctl
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

### Future schema v2: uninstall and guarded power-key reveal

**Decision:** keep schema v1's exact set of commands and the guarantee
`secrets_included: false`. Extend the contract in **schema v2**, in the
Go installer integration milestone, with two separately reviewed actions:

- **`uninstall`**: explicit confirmation; remove only the allowlisted
  managed agent files and units, restoring service state as appropriate
  and preserving `/var/lib/linux-host-agent/installation-id` and
  `control-token`, plus the v2 ownership record. Use journal/snapshot
  recovery and verify that a subsequent v2 reinstall can reuse the
  SmartThings device identity (P06). Do not invent an untested delete path.
- **`reveal_power_key`**: only after a deliberate Show/Copy action,
  after checking the remote-power feature is enabled. Read the protected
  key through the privileged boundary; return it only on a dedicated
  redacted-from-logs response path with `secrets_included: true`.
  Do not include key material in status, plan, normal install output,
  error reports, debug logs or crash diagnostics. Define a safe clipboard
  lifetime, visibility and clear/copy behavior in the Go UI (P02).
  A secret-revealing operation cannot share schema v1's no-secrets
  response contract.

The v2 extension will be implemented/tested **before** the Go wizard
claims complete Windows Setup parity. It is deliberately not enabled by
PR #77; older v1 readers will reject the new schema rather than
silently interpreting a secret-bearing response.

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
responses. Additional launcher tests cover rejection of Python 3.6/3.9,
acceptance of 3.10+, shell syntax and the same manual selector precedence,
including a fake unsupported `python3` with an available `python3.11`.
There is no sudo, real systemd invocation or live agent write.

**Release acceptance still required:**

1. Implement the agreed version-verified, explicitly elevated Go bootstrap
   for the root helper and manifest, including an update/recovery-safe
   replacement of the previous trusted launcher set.
2. Connect the Go wizard's explicit Review/authorization/Execute steps to
   this stdin/JSON contract and add the planned schema v2 actions before
   claiming complete parity, keeping TUI terminal ownership correct.
   **The Go wizard lives in separate draft PRs #67/#72, not on `main`.**
   Do not copy that experimental UI wholesale into this backend PR.
3. Review the implementation and test both normal and crash/recovery
   workflows on actual systemd/Gentoo with reversible snapshots.
4. Only then promote it as the supported Linux installer.

This PR makes the backend recoverable and defines the fixed privileged
endpoint, but **does not yet deploy or invoke it on `hydra`**. It does not
enable an interactive or elevated installer automatically.
