# Linux installer PR #75 — protected payload staging boundary

**Status:** independent DATA-ONLY milestone (not a working privileged installer).  
**Production behavior:** unchanged. No sudo/polkit, installed agent/service,
systemd, persistent UUID, token, firewall, networking, WOL or hub interaction.

## Why the distinction matters

The source-installed Linux agent and `install_core.py` already perform useful
systemd installation and exception-triggered rollback. But running those
scripts as root out of an ordinary user's checkout, untrusted temp directory,
or an unverified unpacked binary is **not safe**. A root-side hash comparison
is also meaningless if the attacker can supply **both** the code and its
"expected" hashes.

PR #73 provides bounded runtime health checks. PR #74 provides a private
transaction journal. PR #75 introduces an isolated **data-only** foundation
for placing a hash-matched source payload under root control before any
privileged engine is permitted to execute it.

`scripts/payload_staging.py` is a library module, **not** a command-line
program, authorized installer, privileged wrapper, shell script, or service.
Do **not** run it with `sudo` from a repository checkout. No application
files or services are installed by calling it.

## Fixed payload allowlist

Only the ten specific files referenced in `PAYLOAD_FILES` may be staged:

- `agent/linux_host_agent.py` and `agent/power_helper.py`
- the five exact `agent/systemd/` agent/power/Avahi templates
- `scripts/install_core.py`, `scripts/runtime_verify.py`,
  and `scripts/transaction_journal.py`

No arbitrary extra files, shell hooks, Windows binaries, credential state,
installation identity, control tokens, backups or device configuration.
The manifest must name **exactly** this allowlist; every expected digest
must be a lowercase 64-character SHA-256 hex string. Files are capped
at 1 MiB each and 4 MiB total. All content is read and validated in bounded
memory **before** any destination directory is created.

Untrusted source path components are opened with `O_NOFOLLOW` and
directory file descriptors; source payload files must be regular, singly
linked and digest-matched. All source bytes are retained after validation,
so later tampering with the unprivileged source tree cannot affect the bytes
written to the protected stage. There is no shell interpolation or code
execution of source payload.

## Root-owned staging and crash behavior

Future production root-only path (constant, never from a wizard argument):

`/var/lib/computer-host-installer/staging/`

No-follow directory-fd traversal checks the trusted owner and prevents
group/other writes on `/var` and `/var/lib`. New shared system folders
are mode 0755; the application-specific root directories and pending/ready
payload directories are 0700. Modes are set with `fchmod` and `fsync`
independently of process umask. Existing administrator-owned directories
are checked, not normalized.

A private 0600 lock prevents concurrent staging. A uniquely named,
root-only `pending-...` directory receives all staged files as 0600,
with file/directory durability barriers. Each output file is reread from
the protected stage and hashed again. Only after all bytes are verified
does the stage get atomically renamed to `ready-...` and its parent synced.

The return value is a verified *open directory file descriptor*, **not
an execution or installation authorization**. It must be closed by the
trusted caller. There is deliberately no `exec`, `sudo`, `subprocess`,
`systemctl` or installation entry point in this PR.

Any abandoned `pending-...` marker or existing `ready-...` stage
blocks a new stage. The module does **not** silently remove root state or
offer an unsafe recursive cleanup API. Cleanup and reuse must be part of
a later trusted transaction-recovery design. A failing digest requires
zero destination writes; a disk/write failure after creation may leave
an explicit incomplete stage and must not be called success.

## Trust boundary: intentionally *not* implemented yet

The `trusted_hashes` argument is a dependency provided by a **trusted,
root-owned caller**. The module proves equality to that argument but
**does not authenticate the manifest, the publisher or a downloaded
release**. Tests inject hashes for disposable fixtures only.

Before production installation is enabled, a future separately reviewed
root-owned launcher must:

1. Be installed/authorized through a documented, verified distribution
   path, not executed as root from the user's writable Go/source folder.
2. Pin or independently authenticate the **exact** payload hashes,
   version, bundle identity and publisher provenance. A self-reported
   hash file within the same attacker-writable bundle is insufficient.
3. Require explicit user authorization (sudo/polkit) with the TUI paused,
   without capturing credentials, shell-interpolating input or starting
   a privileged program from a writable parent.
4. Accept only a bounded, versioned request schema (operation and
   allowlisted options), never arbitrary root destinations, Python
   executables, script paths, shell text or systemd unit names.
5. Check the finished staged files **again** under trusted directory
   handles before executing; keep the stage private until transaction
   completion or validated recovery.
6. Coordinate with the existing manual installation lock
   `/run/lock/linux-host-agent-install.lock` and PR #74 journal for
   both staged and pre-existing installs.
7. Preserve the original install/upgrade/rollback semantics, including
   disabled/stopped services, private key/UUID and feature opt-ins.
   Integrate PR #73's read-only verifier only after the recovery gate
   and trusted comparison have been implemented.

A separately downloaded file and its checksum from the *same untrusted
origin* do not prove authenticity. Release provenance/signature and
offline verification remain mandatory acceptance work.

## Tests and expected limitations

`tests/test_payload_staging.py` uses only a temporary non-root fixture
tree. No host root path, agent process or systemd service is modified.

Tests cover the complete payload, exact allowlist and digest validation,
source changes after validation, missing/oversized/tampered files,
symlinks/hardlinks/FIFOs, parent directory permission checks, umask 077,
preexisting parent modes, concurrent-stage lock refusal, interrupted
writes/pending markers and descriptor lifecycle.

GitHub CI exercises Python 3.10–3.14 and source-only distro tests;
it does **not** certify actual Linux distribution privilege policies,
systemd PID1, hardware WOL, SmartThings pairing or sudden power-loss
durability.

**Do not treat this PR as a full root privilege handoff or release the Go
wizard as an installing product based on this milestone alone.**
