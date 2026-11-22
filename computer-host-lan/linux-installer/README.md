# Computer Host LAN — Linux wizard preview (development only)

> **NO INSTALLATION POSSIBLE.** This Go program is an experimental installer
> frontend. It has two modes:
> - **Demo (default):** all information is simulated. No inspection occurs.
> - **Live read-only (`-live`):** runs the versioned JSON `inspect` / `plan`
>   operations from the merged Python `scripts/installer-api.sh`. It reports
>   real Linux/service/Avahi/interpreter state and prospective *file* changes.
>   No installation or upgrades, network discovery, power changes, WOL
>   configuration, sudo, credentials or root-private recovery inspection.

Neither mode installs, repairs, upgrades, removes or configures an agent. The
existing `scripts/install-agent.sh` remains the supported installer.
The wizard is **not** part of Computer Host LAN v1.0.0-rc.2.

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
go run . -live -preview

# Real inspection + editable prospective file plan
go run . -live
go run . -live -accessible
```

The default backend is `../scripts/installer-api.sh` **relative to the current
working directory**. If you start the compiled binary elsewhere, pass
`-api /absolute/path/to/computer-host-lan/scripts/installer-api.sh`.
The launcher must be executable (`100755`). The Go controller uses
`exec.CommandContext` with an absolute resolved executable path, argv
(not shell-composed strings), a 12-second timeout, bounded JSON output
and disabled Python bytecode writes.

`-live` refuses wrong JSON schemas, unknown fields, unsupported error codes,
paths outside the existing installer allowlist, `secrets_included: true`,
`changes_applied: true` or `runtime_verified: true`. Backend failures are
shown only as safe codes, never as unfiltered subprocess output.

The live wizard displays **real compatibility status**, then offers power
settings *for the prospective plan only*: preserve (default), enable and
disable. It can optionally preview a **systemd WOL interface pin** after
validating the NIC via the Python API. Pinning is **not** the same as
configuring persistent WOL or testing physical hardware support. Hub
discovery and manual pairing are not implemented in live mode; the simulated
hub-selection UI remains in the demo only.

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
   go run . -live -preview
   go run . -live
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
checks Go unit tests and static analysis, and uploads a **7-day-retained,
non-release test binary** for Gentoo hardware acceptance.

## Deliberately deferred

A privileged read-only recovery-status helper, durable root-owned journal
and safe recovery, trusted bundled payload and sudo boundary, post-install
health/identity checks, real SmartThings hub discovery/onboarding,
custom-port preservation and hardware WOL remain separate future work.
Those are **not** implied by successful read-only inspection.
