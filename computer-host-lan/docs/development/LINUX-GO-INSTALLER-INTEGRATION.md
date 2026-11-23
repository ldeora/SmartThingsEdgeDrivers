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
Only then does the normal-user process call `sudo` to start a separate
one-shot `-root-bootstrap` process. It never renders the TUI as root,
captures a password or feeds the sudo password on stdin. The root
process reads only an allowlisted schema-v1 JSON object. Noninteractive
sudo uses `-n` and cannot wait for a password prompt.

No source checkout is needed to inspect or plan: the executable also
embeds a **separate read-only Python inspection bundle** and runs that
bundle unprivileged from a disposable 0700 directory. The privileged
`installer_root.py` is **never** extracted or invoked from that preview
location.

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

After explicit sudo authorization the trusted Go bootstrap:

1. Validates its fixed JSON schema. The caller may request only
   `install`, `upgrade`, `repair`, `status` or `recover`. It cannot
   select a root destination, executable, source path, Python interpreter,
   raw shell command, UUID, key or port.
2. Takes the same exclusive manual installation lock as `install_core.py`.
   On an existing trusted installation, calls its **old** installed
   `status` action. It **refuses to replace that version** if the journal
   requires recovery. The user must first explicitly run `-recover`
   with the old helper. No helper changes mid-transaction.
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
   the bootstrap refuses an ambiguous update rather than deleting a
   potentially necessary recovery helper.
5. **Releases the shared manual lock** before executing the installed
   `installer-entry.sh`, because the Python transaction backend must
   reacquire the same lock itself. It uses a fixed system PATH and
   selects Python >=3.10 without changing system Python symlinks.
6. The Python backend stages the embedded payload against the new trusted
   manifest, snapshots only the managed files, applies/upgrades,
   verifies systemd + local HTTP health, and either commits or rolls
   back. UUID and control token are agent-owned and never recreated by Go.
7. On a verified completed install the old helper set is retired;
   if a failed install leaves a pending journal the **new** matching helper
   remains in place for explicit recovery. An error with a fully clean
   journal restores the previous helper version.

A verified installation can still finish with an optional
`installed_cleanup_required` status. That is **not** a failed agent
install; the terminal journal must be cleaned using the matching helper.

## Scope and remaining parity work

This milestone enables a first real **install/upgrade** path, including
review, sudo handoff, fixed bootstrap, payload staging, durable
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
