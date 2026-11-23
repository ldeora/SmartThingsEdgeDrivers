# Computer Host LAN — Go installer bootstrap and execution (PR #78)

**Status: draft, integration and test only.** This PR brings the latest
reviewed Go UI from draft PRs #67/#72 onto the post-#77 backend and adds a
real, explicitly authorized installer flow. The branch is a self-contained
review target based on current `main`; do not merge the old stacked UI
branches independently on top of it.

## User workflow

The original `-preview` and `-live` modes remain **strictly read-only**.
The new installation path is deliberately distinct:

```sh
# Read-only, no sudo:
./computer-host-linux-installer-test -live -preview -api ../scripts/installer-api.sh

# Live guided installation from a reviewed, verified Go binary:
./computer-host-linux-installer-test -live -install

# Plain-text accessible alternative:
./computer-host-linux-installer-test -live -install -accessible

# SSH with no local polkit agent, explicitly use su and its root password:
./computer-host-linux-installer-test -live -install -accessible -elevation su

# Explicit repair of a previously interrupted transaction, with confirmation:
./computer-host-linux-installer-test -recover
```

`-live -install` performs read-only inspection, optional hub discovery and
planning **before any authorization**. It uses the same beginner-oriented
Go Huh form: Welcome → Hub → Power → optional NIC → Review. The hub
IP is **advisory**, not pairing, authentication or a firewall allow rule.
Monitoring-only is the default, and an upgrade preserves its previous
remote-power setting unless changed.

After the form **has exited and restored the terminal**, the user must
type the literal `INSTALL` confirmation (including plain-text mode).
Only then does the normal-user process select an installed
administrator authorization method and start a separate one-shot
`-root-bootstrap` process. The preference order is **sudo**, **doas**,
**run0** (systemd/polkit), then **interactive `su root -c`**. It uses
fixed executable paths, never interpolates the JSON into shell arguments,
and never runs the TUI as root or collects an administrator password.
A declined authorization does **not** silently cause an automatic retry
with a different provider.

`sudo`, `doas`, and `run0` forward the same bounded schema-v1
JSON on stdin; authentication happens via TTY or polkit. `run0`
uses `--pipe`, `doas` and `sudo` use `-n` without a terminal,
and `run0` uses `--no-ask-password` in noninteractive mode.

**`su` is different:** on util-linux, PAM may read the root password
from *stdin*, even when the user has a controlling TTY. Feeding the
installation JSON there would fail authentication without a usable
password prompt. Therefore the interactive `su root -c` fallback
leaves **stdin attached to the user's terminal** and passes only the
small, non-secret request using
`-root-bootstrap -request '<strictly shell-quoted JSON>'`.
The normal Go process verifies the request schema before elevating.
The root Go process decodes this argument through the **same bounded,
strict schema-v1 JSON decoder** (4096 bytes maximum, allowlisted keys)
used for piped requests. The command-line argument can be visible in
process listings: it contains **only** operation, power option and
interface name. The private UUID and control key are explicitly
excluded from schema v1 and must *never* be added to this path.
The `su` fallback is only available with a real terminal; the local
distribution's PAM conversation must be verified in the first live test.
Its password prompt and input are never buffered as application
diagnostics.

**SSH caveat:** The default provider remains `auto`, selecting installed
`sudo` → `doas` → `run0` → `su`. A headless SSH session can have
`run0` installed but lack the polkit agent/authorization of a local
desktop session, so `run0 --pipe` may be denied even when `su root`
works. Use the explicit **`-elevation su`** option (also supported
with `-recover`) to request just `su`, instead of deleting/renaming
`run0`, changing polkit policy, or retrying authentication silently.
The override is accepted only for installation or recovery, not preview,
demo, or internal root-bootstrap mode. It cannot choose arbitrary shell
commands; invalid/unavailable providers stop before elevation.
Over SSH allocate a pseudo-TTY (`ssh -tt`) for PAM's password prompt.

On Gentoo acceptance `hydra`, local Go tests and the strict read-only
preview passed with Go 1.27.3 and Python 3.14.10. Unprivileged protocol
classification returned `v2`; an absent optional installer ownership
marker is not by itself a blocker for clearly classified existing v2
managed files. The `run0` JSON probe over SSH was denied by polkit,
which is why this explicit non-default provider option is supplied.
A root-private journal/status check is still required before any live
upgrade; the read-only wizard reports that state as `UNKNOWN`.

No source checkout is needed to inspect or plan: the executable also
embeds a **separate read-only Python inspection bundle** and runs that
bundle unprivileged from a disposable 0700 directory. The privileged
`installer_root.py` is **never** extracted or invoked from that preview
location.

The regression test executes the shell-quoted `su -c` payload
against an unprivileged test script (no real authentication), checks
that the exact JSON survives quoting, and ensures the terminal is
reserved for PAM rather than the request. CI does not enter a real root
password or make any host changes.

## Gentoo Python-exec root launcher regression (physical test 2026-11-23)

The first real authorized `-elevation su` attempt on Gentoo `hydra`
authenticated correctly but stopped after installing the fixed root-owned
helper directory, **before** Python transaction staging. The old entry
launcher had `PATH=/usr/sbin:/usr/bin:/sbin:/bin`, yet only accepted
`/usr/bin/*|/bin/*` results from `command -v python3`. On Gentoo,
`command -v python3` returned `/usr/sbin/python3`, a valid python-exec
wrapper resolving to `/usr/bin/python-exec2c`. All installed Python
3.12–3.14 interpreters passed `-I -S -B` independently.

The corrected launcher permits all four **fixed root-controlled PATH
directories**; it retains Python 3.10+ checking, `-I -S -B`, a sanitized
environment and the independently root-owned launcher/manifest checks.
No Python default, PATH, Gentoo wrapper or polkit configuration should be
changed by the operator.

The first attempt left a root-owned helper using the old launcher. An
exact SHA-256-gated, read-only status fallback was temporarily introduced
so that the reviewed corrected launcher could be promoted without modifying
the installed agent. After the successful `hydra` upgrade, the external
review noted that this was only compatibility code for an unmerged draft.
The narrow legacy fallback, checksum and dedicated fixture were therefore
**removed** from this PR; root now uses only the current installed helper.

### Follow-up from the second physical attempt: Python backend guard

After updating to the corrected shell launcher, the second `hydra` test
with `-live -install -accessible -elevation su` passed the interactive
wizard and root-owned helper selection but returned the protected fixed
error `invalid_request`. The backend has an **independent** validation
of `InstallRequest.python_bin`: it previously allowed only
`/usr/bin/` and `/bin/`, even though the shell launcher already allowed
`/usr/sbin/` and `/sbin/`. The selected Python entrypoint is provided
internally as `sys.executable`; no arbitrary interpreter is supplied
from the wizard request. This mismatch can reject valid Gentoo Python
wrappers in the backend after the launcher successfully authenticates.

The backend now uses the same four fixed system prefixes as the shell.
It still disallows relative paths, traversal, spaces and interpreters
outside those prefixes. A fixture-only full v2 upgrade regression runs
with `python_bin=/usr/sbin/python3`, existing private identity, and
active/enabled service state. A separate privileged-router regression
checks the dispatch path using the same Gentoo interpreter value.
These tests do not invoke a real agent or systemd.

The next physical read-only check gave the decisive Gentoo interpreter
values: the root launcher selects `/usr/sbin/python3`, but Python's own
`sys.executable` is **`/usr/lib/python-exec/python3.14/python3`**.
Therefore the second attempt still returned `invalid_request`, and the
initial four-prefix fix on `InstallRequest` alone was insufficient.

**Corrected shell-to-Python handoff:** `installer-entry.sh` now supplies
`--selected-python "$PYTHON_BIN"` when executing the fixed root-owned
`installer_root.py`. This is the *same interpreter* already checked
under the fixed PATH with Python 3.10+ and `-I -S -B`. The Python
entrypoint verifies the argument is an exact member of the 24 fixed
system-directory/candidate-name combinations and hands it to the
transaction backend for systemd unit generation. It does **not** use
`sys.executable` or allow arbitrary `/usr/lib` executables. It still
rejects a missing handoff for install/upgrade/repair, while permitting
the old `--request-stdin` form only for the trusted read-only
`status` action. Explicit `recover` also requires the new trusted
interpreter handoff. The status-only direct invocation was used during the earlier Gentoo
diagnostics. The deprecated launcher-compatibility fallback is no longer
part of the production bootstrap.

The initial post-failure status check ran the *old installed shell*
and stopped on its Python-selection error because `set -e` was active.
That did **not** inspect the protected journal. Before retrying, invoke
the installed, root-owned Python entrypoint with a fixed system Python
and **only** a `status` request, confirm transaction state `none`,
and check active agent/service state. Never delete old helper or journal
directories manually.

## Third physical attempt: pre-apply abort and bounded stage diagnostics

The third root-authorized `hydra` run (`fa48f77`, Gentoo 3.14,
`-elevation su`) passed the wizard, selected-Python handoff and
privileged request validation, but returned the protected controller
error **`aborted`**. The controller emits this only when the durable
transaction phase was still `INSPECTED`, `STAGED` or `SNAPSHOTTED`;
managed agent files and service units have not yet been applied. The
controller attempts to retire the current stage and terminal journal
before returning `aborted`; inspect their *actual status* before any
additional operation. A backup snapshot may still exist, even if the
transaction state is `none`.

Historically `aborted` masked every pre-apply exception, including
different root-only prerequisites not exercised by ordinary CI fake-root
fixtures. To avoid repeated blind installations, the backend now emits
**only** a fixed, non-sensitive `failure_stage` when it can prove a
clean pre-apply abort:

- `payload`: source payload authentication, trusted staging and
  stage readback;
- `existing_state`: read-only pre-existing service/identity checks
  and internal request consistency;
- `plan`: generation of approved managed-file changes;
- `snapshot`: pre-apply backup, durability and journal transitions.

The enum is carried inside the same schema-v1 authenticated root JSON
error response and validated by both root Go and unprivileged wizard
code. Python never serializes the raw exception, file names, addresses,
UUID/token, snapshot names or journal internals; an unknown field value
is rejected, not echoed. The UI labels the failing *stage*, not a
guessed root cause. Older helper responses without the optional field
remain compatible.

### Fourth-attempt blocker reproduced: stale Btrfs directory enumeration

The next `hydra` attempt (commit `62596c7`) returned
`aborted` with the new fixed `failure_stage: payload` classification.
Before further installation, the installed root-only `status` command
reported `privileged_transaction_state: none`. All **10/10** embedded
payload SHA-256 hashes matched the root manifest; staging ownership,
permissions and the empty `stage.lock` were correct, with no leftover
entries. The existing agent and power socket were active.

An **isolated root-owned fixture in /var/tmp**, without changing live
agent files, reproduced `StagingError: incomplete staged payload`.
Inspection of the pending directory proved that **all 10 files were
physically present**. Opening a **new directory descriptor** and
running the same `_inspect_tree` verification succeeded. The
implementation previously enumerated the stage through a descriptor
opened before the files were populated; that directory stream could
return an incomplete listing on the tested Gentoo/Btrfs host.

The repair reopens an independent, descriptor-relative directory stream
with `openat(fd, ".")` for both verification and retirement, retaining
the no-follow, fixed-path and ownership checks. A portable regression
test simulates the stale original descriptor and checks staging, repeated
verification, retirement and journal cleanup. The authoritative Python
module and embedded Go bundle are synchronized.

### Physical `hydra` upgrade acceptance (commit `9513c78`)

The updated Python tests passed **29/29** on Gentoo/Btrfs, the Go tests
and build passed, and a local filesystem fixture completed staging,
hash verification, source readback, retirement, and journal cleanup.
The supervised root-authorized `-live -install -accessible -elevation su`
upgrade then reported **`Computer Host LAN: installed`**. The wizard
selected the discovered hub and preserved existing power-control settings.
The previously installed device identity was verified, both the agent and
power socket remained active, and the local v2 HTTP agent reported
`0.4.6-rc.2`. The installed root-owned protected `status` endpoint
reported `privileged_transaction_state: none` after upgrade.
No private identifier or control key is included in this record.

### Independent review remediation (post-acceptance)

The external reviewer found no privilege-handoff vulnerability, but
identified failure-path gaps not exercised by the healthy host upgrade.
Follow-up commits in this draft:
- remove the Go **120-second process timeout** for all mutating
  install/upgrade/repair/recover operations, retaining it for read-only
  status; bound individual `systemctl` calls in Python instead;
- map a helper crash without JSON to **`recovery_required`** when a
  subsequent trusted read-only status reports an outstanding transaction;
- reopen fresh directory streams in `transaction_journal.py` for both
  temp-file discovery and cleanup, preventing the Btrfs stale-handle
  case from hiding uncertain journal writes or leaving unreaped temp files;
- remove the draft-only Gentoo launcher fallback and update the binary
  trust documentation.

The isolated journal regressions simulate old descriptors that omit
post-open temp files. These safeguards require successful CI and
independent re-review before merge. Orphaned initial-journal temp files
still lack an integrated verified recovery path, and the shared
`/run/lock` namespace remains subject to local pre-creation denial of
service; both remain tracked follow-ups. Never manually delete private
snapshots, helpers, journal files or stage markers.

## Version-pinned Go binary as the bootstrap trust anchor

The downloaded Go executable must be verified against a trustworthy
release reference *before* user grants sudo. A checksum next to an
untrusted binary is not publisher authentication. No native DEB/RPM
package is assumed.

The Go source embeds the exact main-branch files under
`linux-installer/bundle/`. A Go regression test compares **every embedded
Python/helper/unit file byte for byte** to the authoritative file under
`computer-host-lan/`. When any original backend or agent file changes,
the bundle must be updated in the same reviewed commit; CI rejects stale
copies. The Go binary calculates its **root-installed manifest** from the
embedded ten-file agent payload; no manifest supplied from an arbitrary
checkout can change the expected hashes.

After explicit administrator authorization the trusted Go bootstrap:

1. Validates its fixed JSON schema. The caller may request only
   `install`, `upgrade`, `repair`, `status` or `recover`. It cannot
   select a root destination, executable, source path, Python interpreter,
   raw shell command, UUID, key or port.
2. Takes a separate, root-owned exclusive **bootstrap lifetime lock**
   at `/run/computer-host-lan/bootstrap.lock` (under a root-owned
   mode-`0700` directory) over the whole
   version-change and Python execution. Within that lock, it also takes
   the existing **manual installation lock** used by `install_core.py`
   while swapping files. On an existing trusted installation, calls its
   **old** installed `status` action and refuses replacement when its
   journal requires recovery. The user explicitly runs `-recover`
   with that helper before retrying; no second Go bootstrap can swap
   helper versions underneath an ongoing Python transaction.
3. Creates a fixed root-owned `/usr/libexec/computer-host-lan.next`
   directory, writes and fsyncs the version-matched Python modules,
   `installer-entry.sh`, ten-file agent payload and generated
   `trusted-payload.json`. Python helpers are 0644, the entry script
   0755, and the payload resides in a private directory with 0600 files.
4. Moves the previous trusted helper to
   `/usr/libexec/computer-host-lan.previous` and promotes the complete
   staged set with rename/fsync. It restores the old set if promotion
   fails. A crash with the older directory temporarily renamed away is
   reconciled on the next bootstrap attempt, before another installation.
   If both old and new locations remain after an interrupted swap,
   the bootstrap first requires the **currently installed helper** to
   confirm no transaction is pending before retiring the older copy.
   A root-owned partial `.next` stage is safely discarded and rewritten
   on retry; an incomplete journal is never bypassed.
5. **Releases the shared manual installation lock** before executing
   the installed `installer-entry.sh`, because the Python transaction
   backend must reacquire it. The separate **bootstrap lifetime lock
   stays held**, preventing concurrent Go helper replacement. It uses a
   fixed system PATH and selects Python >=3.10 without changing the
   distribution's Python symlinks.
6. The Python backend stages the embedded payload against the new trusted
   manifest, snapshots only the managed files, applies/upgrades,
   verifies systemd + local HTTP health, and either commits or rolls
   back. UUID and control token are agent-owned and never recreated by Go.
7. On a verified completed install the old helper set is retired,
   but only after **reacquiring the manual installation lock** and
   rechecking the protected journal. If a failed install leaves a pending
   journal the **new** matching helper remains for explicit recovery.
   An error with a fully clean journal restores the previous helper
   version under that same lock. A stale root-owned
   `computer-host-lan.failed` is safely checked and retired before
   the next unsuccessful upgrade needs that name. Helper retirement
   failure after a successful install is `installed_cleanup_required`,
   never a false installation failure.

A verified installation can still finish with an optional
`installed_cleanup_required` status. That is **not** a failed agent
install; the terminal journal must be cleaned using the matching helper.

## Structured failure and user guidance

The installed Python helper already returns a redacted schema-v1 JSON
error envelope on stdout even with a nonzero process exit. The Go root
bootstrap now forwards that JSON **before** returning nonzero, and
fills the known requested operation (which Python intentionally omits
on failures). The normal-user wizard **parses stdout first**, even if
the elevation process exited unsuccessfully, and provides specific
help for:

- `installation_busy`: another installation/recovery holds the lock
- `rolled_back`: previous files/service state were restored; review
  prerequisites before retrying
- `recovery_required`: explicitly run the wizard with `-recover`;
  never delete its protected journal or backup to bypass the guard
- `adoption_required`: inspect older retained v2 state, then use the
  manual `--adopt-retained-state` recovery option
- `unsupported_python`: install a compatible system Python
  (3.10 or later) without changing the distribution's default symlink

If elevation was denied, the helper returned no valid JSON, or a
response is unrecognized/secret-bearing, the wizard shows a **generic
authorization/bootstrap failure** without printing arbitrary stderr,
UUIDs, control keys, backups or other private content. Go-only
preparation failures use fixed error codes such as
`bootstrap_failed` and `installation_busy`.

## SmartThings discovery and firewall warnings

The installation **Review and completion screens** show an explicit
warning whenever `avahi_discovery` is not `passed`: merely starting
a local HTTP listener does not prove that the hub can discover its
`_computerhost._tcp` service. The wizard also makes a bounded
**read-only** `systemctl is-active --quiet firewalld.service` probe.
If firewalld is active, both screens warn that inbound TCP 8765 might
need an explicit hub-scoped firewall rule before the user relies on
**Add device → Scan nearby**. The wizard **never** adds a firewall rule
without separate explicit consent. If the probe is unavailable, it
does not assert that no firewall is present.

## Scope and remaining parity work

This milestone enables a first real **install/upgrade** path, including
review, explicit elevation handoff, fixed bootstrap, payload staging, durable
rollback, crash recovery and first-use onboarding instructions. It
does **not** yet provide full Windows Setup feature parity:

- No schema-v2 `uninstall` operation; the old manual uninstall remains
  available with retained ID/key. Build an explicit journaled uninstall
  before presenting it in the wizard.
- No masked/consent-driven power-key reveal or clipboard copy.
  `control-token` remains strictly private and is never emitted into
  stdout, logs or diagnostic JSON. Implement the planned schema-v2
  `reveal_power_key` separately.
- No persistent NIC WOL setup, no firewall rule and no automatic hub
  pairing. Hub selection remains a user aid. The existing Avahi
  `_computerhost._tcp` service and TCP 8765 are unchanged; network
  policy on firewalld hosts may still require an explicit later feature.
- No publisher signing/authentication is added by this draft. The CI
  artifact is **test-only**, not a production release.
- Gentoo/Btrfs `hydra` has completed a supervised upgrade (PR #78)
  with preserved identity and clean protected journal. Clean installations
  and interrupted/recovery paths still require broader distro acceptance.

The user should not delete an interrupted wizard journal or a
`computer-host-lan.previous` directory manually. A recovery failure
is a reason to stop and preserve these files, not to bypass safeguards.

## CI acceptance

The Go integration workflow runs `gofmt`, `go mod tidy -diff`,
unit tests, race tests, vet, existing PTY/accessible/read-only smoke
tests and the new embedded parity/root-request/confirmation tests.
Python and Linux-distro source workflows continue unchanged.

The fixed privileged path is deliberately exercised through **non-root
filesystem fixtures** only in CI. Actual sudo/systemd and kernel crash
recovery require a separate physical acceptance on a reversible test
host. Avoid creating any user, service, power socket or private key
merely to test the new Go interface.

## Follow-up: orphan journal recovery and shared installer lock hardening

The separate post-#78 recovery/lock-hardening PR closes a specific
journal dead end without making a new install silently auto-recover.

**An interrupted initial journal write:** The transaction creates and
syncs its first `INSPECTED` record BEFORE staging any payload, snapshotting
targets, or applying service/file changes. If the first write fails before
the journal rename, a protected `.wizard-journal-*` temporary file may be
left behind with no `journal.json`. Read-only `status` correctly reports
`recovery_required`, but the previous `-recover` implementation could not
resolve that state.

Explicit `-recover` now allows cleanup **only** under the normal shared
manual installer lock AND an exclusive protected journal lock, after
confirming that there is no persistent journal, **exactly one** temp marker,
and **no staged payload**. It performs another no-stage check under the
journal lock. Recovery additionally opens that temp file without following
links, checks its owner/type/mode/link count and bounded size, and requires
its bytes to be a prefix (including the empty prefix) of the **canonical
initial `INSPECTED` journal record**. A complete non-initial
record, or a partial record that already diverges from that canonical
prefix, is never discarded merely because `journal.json` is missing.
This allows genuinely interrupted
first writes while failing closed on corrupted later-phase state. No agent
files, credentials, services or snapshots are modified by this branch.
Multiple markers, any pending/ready stage, a durable incomplete journal,
or any invalid record content require investigation and are preserved.

**Locks:** Go's bootstrap and manual shared lock now open with
`O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`, reject symlinks, nonregular
files, hardlinks, incorrect owners and group/world-writable files, and
verify the opened inode matches the visible path. The manual Python CLI
now applies equivalent checks, while retaining existing root-owned
`0644` lock compatibility. Neither implementation truncates, replaces
nor chmods an existing valid lock. The journal already uses fd-relative
nofollow locking.

**Remaining shared-lock limitation:** A user on a system with world-writable
`/run/lock` can still pre-create a user-owned *regular file* with the
fixed legacy `linux-host-agent-install.lock` name, denying service to
the installer. The installer fails closed and does not unlink a file it
cannot trust. Fully removing that denial of service requires a
coordinated migration of the shared lock namespace (including older
manual installers). A signed, independently authenticated release
binary and additional distro testing remain separate release gates.

## Follow-up: private bootstrap lock and actionable shared-lock errors

The Go wizard's **bootstrap lifetime lock** is independent of the
shared manual-installer lock and has no public release history. It now
lives at `/run/computer-host-lan/bootstrap.lock`, inside a root-owned
directory required to have mode `0700`. The bootstrap creates that
directory under a validated `/run` parent (without following symlinks),
then rejects any existing directory with unsafe ownership or mode.
This prevents ordinary local users from pre-creating or replacing the
**bootstrap** lock on distributions where `/run/lock` is world-writable.
An earlier internal test build used
`/run/lock/computer-host-lan-bootstrap.lock`; it is not reused by the
new unreleased wizard, and must not be deleted while an old installer
might be running.

The **legacy shared lock** remains
`/run/lock/linux-host-agent-install.lock` because the Go wizard,
Python backend and manual installer must continue to exclude each
other. All implementations reject unsafe lock objects; the privileged
wizard now returns only the fixed `unsafe_lock` code instead of
`bootstrap_failed` or a generic environment failure when the lock is
untrusted. The unprivileged UI provides the two fixed diagnostic paths
and directs the user to confirm no installation is running and ask an
administrator to inspect the offending file. The manual installer uses
an equivalent, human-readable error without exposing private runtime
state. **Neither tool removes a questionable lock automatically.**

A local pre-creation denial of service against the *shared* legacy lock
remains possible until its consumers are migrated together. This PR
does not remove that compatibility safeguard or claim to close that
remaining denial-of-service case.
