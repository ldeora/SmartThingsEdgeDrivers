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

Because the first attempt already left `/usr/libexec/computer-host-lan`
installed with the defective shell launcher, subsequent upgrades would
otherwise fail the pre-replacement status check. The Go bootstrap
therefore recognizes **only the exact SHA-256** of that reviewed old
shell script in the fixed root-owned helper directory. If and only if
its normal status call fails with the launcher's exact, non-secret
missing-Python message, it invokes **only** the existing root-owned
`installer_root.py --request-stdin` with action `status` through
a compatible system Python found in fixed system paths. That module
continues to enforce ownership, isolated execution and manifest
validation. The protected transaction state must be `none` before
Go may promote the repaired helper; a pending journal, unknown launcher,
untrusted paths or invalid JSON **fails closed**. This is not an
install/upgrade/recover bypass and never accesses or prints the private
ID or control token.

CI now includes the exact archived legacy launcher checksum, a
read-only status test against the root-owned helper, and an isolated
runner simulation that replaces the old launcher **only after** reading
its protected status. No live agent is touched by those CI tests.
The physical host still requires a fresh supervised upgrade test after
the repaired reviewed binary is rebuilt.

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
   at `/run/lock/computer-host-lan-bootstrap.lock` over the whole
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
- No physical installation has been attempted on `hydra` until
  independent review and a reversible acceptance plan.

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
