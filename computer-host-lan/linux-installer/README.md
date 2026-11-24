# Computer Host LAN — Linux wizard preview (development only)

> **PR #78 integration (draft, not a published installer):** The wizard now
> has an explicitly confirmed `-live -install` mode. All original demo,
> `-live -preview` and plain `-live` paths remain read-only. The real
> installation path has passed a supervised upgrade on Gentoo/Btrfs hardware,
> but is still **NOT RELEASE-CERTIFIED** or independently signed.
> Read [the Go installation/privilege contract](../docs/development/LINUX-GO-INSTALLER-INTEGRATION.md)
> before considering a supervised test on a reversible host.

## Actual install/upgrade entry point (new, review pending)

The standalone Go executable embeds the version-matched Linux agent,
privileged transaction engine, manifest, and read-only inspector.

**Binary trust boundary:** The elevated process executes the very Go
binary selected by the normal user. As with `sudo ./installer`, a process
running under that same account could replace a user-writable binary before
administrator authorization. Keep the executable and its parent directory
protected, and use an independently authenticated release binary when one
becomes available. A SHA-256 file shipped beside an unsigned CI artifact
does **not** authenticate the publisher.

**Installer locks:** The unreleased Go wizard stores its lifetime lock
inside the private root-owned `/run/computer-host-lan/` directory (mode
`0700`). The legacy shared manual-install lock remains at
`/run/lock/linux-host-agent-install.lock` for cross-version exclusion.
If the wizard reports `unsafe_lock`, confirm no installation or recovery
is active and have an administrator inspect those fixed locations; do
not remove a lock automatically or during an active transaction.

After presenting the familiar hub, power and advanced-network choices, it
requires typing `INSTALL`, then requests administrator authorization
**after the terminal form has closed**. The bootstrap installs its own
trusted root-owned helper set and executes the existing Python
installation backend. The default provider is auto-detected; remote SSH
sessions without an interactive polkit agent can explicitly select `su`.

```sh
# Read-only; no privilege:
./computer-host-linux-installer-test -live -preview -api ../scripts/installer-api.sh

# New installation/upgrade, only after review and with explicit authorization:
./computer-host-linux-installer-test -live -install

# Plain text, requires literal INSTALL at the final screen:
./computer-host-linux-installer-test -live -install -accessible

# Remote SSH with a PTY and root-password su, even when run0 is installed:
./computer-host-linux-installer-test -live -install -accessible -elevation su

# Resolve a previously interrupted operation with the existing installed helper:
./computer-host-linux-installer-test -recover

# Guided uninstall (requires a terminal, literal UNINSTALL and administrator authorization):
./computer-host-linux-installer-test -uninstall
```

### Journaled uninstall (development only)

The separate `-uninstall` mode removes the managed agent files, systemd
units/drop-ins and Avahi service, after verifying that the units are
stopped and the enabled units disabled. It retains the private installation
ID and control key, v2 ownership marker, linuxhost account, root-owned
recovery helper, historical snapshots, and operator-managed network/WOL
and firewall configuration. It does not unpair SmartThings. The existing
device goes offline until removed manually or the agent is reinstalled.
No changes are authorized until a submitted literal `UNINSTALL`
confirmation and administrator authorization. Use `-recover` after an
interrupted transaction: rollback restores the prior installation, while
terminal cleanup never resumes removal. A later uninstall requires
fresh explicit confirmation. The privileged request for uninstall uses
schema version 2 with exactly two fields; existing schema-v1 operations
and the schema-v1 result envelope remain compatible.

This draft still **does not** provide a power-key Show/Copy screen,
automatic SmartThings pairing, firewall changes, persistent WOL
configuration or release-authenticity verification.
Do not treat the test-only CI binary as a production release.
Read the integration document for recovery and first-live-test gates.

---


> **LEGACY PREVIEW MODES ARE NON-INSTALLING.** This Go program now has
> an explicitly authorized `-live -install` draft path, but neither of
> the original preview modes has been changed:
> - **Demo (default):** all information is simulated. No inspection occurs.
> - **Live read-only (`-live`):** runs the versioned JSON `inspect` / `plan`
>   operations from the merged Python `scripts/installer-api.sh`. It reports
>   real Linux/service/Avahi/interpreter state and prospective *file* changes.
>   No installation or upgrades, power changes, WOL configuration, sudo,
>   credentials or root-private recovery inspection. Interactive live mode
>   may optionally query the local Avahi daemon for SmartThings hub candidates;
>   this never contacts or authenticates the hub.

Neither original preview mode installs, repairs, upgrades, removes
or configures an agent. `-live -install` is a **draft** real installer
whose privileged backend has passed CI and completed a supervised physical
Gentoo/Btrfs upgrade with preserved identity and clean protected journal.
Independent review and additional failure/recovery acceptance remain required
before a release.
The existing `scripts/install-agent.sh` remains the supported
production installer. The Go wizard is **not** part of v1.0.0-rc.2.

## Regenerating the embedded bundle

The checked-in `bundle/` is generated from a fixed allowlist of authoritative
agent and script sources. After changing any of those sources, run from
`computer-host-lan/linux-installer`:

```sh
python3 sync_bundle.py
python3 sync_bundle.py --check
go test -run TestEmbedded ./...
```

Commit the generated changes together with the source changes. The generator
refuses unexpected bundle entries instead of deleting them, and `--check`
reports drift without writing. CI checks the generator and independently
runs the existing Go embedded parity tests. This is development tooling,
not a privileged installer step; never run it to repair an installed helper.

## Development and preview

In a **source checkout containing merged PR #68** and the current PR #67
branch, with Go 1.25+:

```sh
cd computer-host-lan/linux-installer
go mod verify
go test ./...

# Original inert UI demo
go run . -preview
go run .
go run . -accessible

# Actual read-only data, no terminal required
go run . -live -preview -api ../scripts/installer-api.sh

# Real inspection + editable prospective file plan
go run . -live -api ../scripts/installer-api.sh
go run . -live -accessible -api ../scripts/installer-api.sh
```

The `-live` mode **requires an explicitly selected backend** via `-api`.
For a downloaded binary run outside the checkout, supply an absolute path,
for example `-api /absolute/path/to/computer-host-lan/scripts/installer-api.sh`.
The unprivileged controller rejects missing, symlinked, non-executable, or
group/world-writable launcher files. Keep the script and its parent checkout
in a trusted directory. The Go controller uses `exec.CommandContext` with a
resolved executable path and argv (no shell-composed command), a **45-second
outer timeout** (covering chained Python and systemctl probes), a **2-second
WaitDelay** for inherited output pipes, bounded JSON output and disabled
Python bytecode writes. All code paths remain strictly read-only.

`-live` refuses wrong JSON schemas, unknown fields, unsupported error codes,
paths outside the existing installer allowlist, `secrets_included: true`,
`changes_applied: true` or `runtime_verified: true`. Backend failures are
shown only as safe codes, never as unfiltered subprocess output.

## Beginner-friendly Linux setup preview

Following the same sequence as the Windows installer, the normal Linux flow
now asks only:

1. **Welcome.** The wizard quietly checks Linux/Python and tells you whether
   an agent is already installed. Full internal diagnostics are available
   separately with `-live -preview`.
2. **SmartThings hub.** Discovery via Avahi happens automatically (when the
   optional `avahi-browse` tool is available). The first discovered hub is
   **preselected**; with one hub, press Enter. With several, choose the right
   one. If none are found, manual IPv4 entry is the default; choosing later
   remains possible. The `_smartthings._tcp` advertisement is not an
   authenticated pairing.
3. **Power control.** Monitoring-only is the default on new systems. Existing
   opt-in power control remains enabled by default on upgrades. Users can
   deliberately change this setting. **Advanced network setup** defaults
   to leaving everything unchanged.
4. **Review.** The normal summary lists the selected hub, monitoring/power
   choice and any advanced interface change in plain language. It does
   **not** show managed-file paths, Python internals or an installation log.
   Diagnostic `-live -preview` retains the technical file-operation plan.

The **network interface input is not shown in the ordinary workflow**.
Choosing advanced networking opens the field with a suggested interface when
one can be identified from the local route table or a single active hardware
interface. Press Enter to accept it, or edit the case-sensitive name. This
suggestion is not proof of wired Ethernet or Wake-on-LAN hardware support;
the preview cannot enable WOL or alter the computer.

This is still a **read-only setup preview**, not an installer. Completion
prints `SETUP PREVIEW COMPLETE — no changes made.` It does not install,
pair, restart the agent, change the firewall or display a power-control key.

The `-live -preview` noninteractive command makes no discovery query.
Full-screen and accessible live modes may send a local mDNS browse request
via Avahi but do not connect to a hub or change any network settings.

The initial read-only inspection **does not claim** recovery state:
`privileged_transaction_state` is always `unknown`. A missing service
file does not prove uninstallation, and existing service status does not
prove a healthy HTTP endpoint. All planned files are prospective,
**none are written**. No service restarts, WOL settings, network sockets
or firewall changes are performed by this program.

## Test on Gentoo (`hydra`)

Since Linux has only one current tester, the first actual-machine acceptance
target is Gentoo + systemd. This is *safe even with your existing live agent*:

1. Fetch the latest PR #67 branch and confirm it includes merged PR #68.
2. In `computer-host-lan/linux-installer`, either build locally with Go
   1.25+, or get the **test-only** statically linked `linux/amd64`
   executable from the PR's successful GitHub Actions `Computer Host LAN
   Linux TUI spike` workflow. The CI artifact is named
   `computer-host-linux-readonly-wizard-test-only` and includes a
   SHA-256 file. It is *not* a signed release.
3. Execute read-only commands (never use sudo):

   ```sh
   cd computer-host-lan/linux-installer
   go run . -live -preview -api ../scripts/installer-api.sh
   go run . -live -api ../scripts/installer-api.sh
   ```

   For a downloaded test-only binary instead:

   ```sh
   sha256sum -c computer-host-linux-readonly-test.sha256
   ./computer-host-linux-readonly-test -live -preview \
     -api /absolute/path/to/computer-host-lan/scripts/installer-api.sh
   ./computer-host-linux-readonly-test -live \
     -api /absolute/path/to/computer-host-lan/scripts/installer-api.sh
   ```

4. Compare `-live -preview` against
   `sh ../scripts/installer-api.sh inspect` and
   `sh ../scripts/installer-api.sh plan`. Verify it reports the actual
   installed service, enabled and running states, Python, Avahi and
   power-drop-in correctly. Try Back, Esc/Ctrl+C, a narrower terminal,
   `-live -accessible` and SSH. Verify nothing was restarted or changed.

**Please do not use this preview to perform an installation.** The Go binary
has no installation command and should never be run as root. If a JSON
report shows an unsafe path or missing prerequisite, inspect manually;
do not bypass the read-only checks.

## Existing demo and accessibility

The original demo remains available unchanged and **does not** run the real
API. It still has simulated TEST-NET hubs, canonical IPv4 validation,
conditional address warnings, and simulated feature settings.

Both modes support `-accessible`, an ANSI-free, plain-text interaction
with `back` and `quit` for machines without a functional full-screen
terminal. Huh v2.0.3's built-in accessible runner currently does not
correctly hide conditional pages. Full-screen mode uses a single
Huh multi-group form and requires a real TTY.

CI tests the original demo on a pseudo-terminal at 80×24 and 60×20,
tests the live API and ANSI-free flow on a real unprivileged GitHub runner,
checks Go unit tests, **`go test -race ./...`**, gofmt and static analysis;
coverage includes concurrent Huh background review/foreground validation,
case-sensitive interface names such as `LAN0`, unsafe launcher permissions,
and child-process pipe timeouts. CI uploads a **7-day-retained, non-release
test binary** for Gentoo hardware acceptance.

## Deliberately deferred

A privileged read-only recovery-status helper, durable root-owned journal
and safe recovery, trusted bundled payload and sudo boundary, post-install
health/identity checks, real SmartThings hub discovery/onboarding,
custom-port preservation and hardware WOL remain separate future work.
Those are **not** implied by successful read-only inspection.
