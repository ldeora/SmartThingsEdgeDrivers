# Linux installer — non-privileged UX experiment

> **EXPERIMENT ONLY — NOT AN INSTALLER.** This Go program does not install, upgrade, configure, discover or connect anything. It does not inspect services, open a socket, read credentials, use sudo, or modify the host. All compatibility, discovery, installation and upgrade information is simulated.

This draft PR is stacked on the [Linux installer design specification](../docs/development/LINUX-INSTALLER-DESIGN.md). It tests wizard interaction and accessibility before privileged operations are designed. It is **not** part of any Computer Host LAN v1.0.0-rc.2 release.

## Try the experiment

Requires **Go 1.25+** and network access to download pinned dependencies on the first build. From the linux-installer directory:

    go mod verify
    go mod tidy -diff
    go run .
    go run . -accessible
    go run . -preview
    go test ./...

The interactive wizard uses **one Huh v2 form with several groups**. Shift+Tab goes back to previous pages; manual IPv4 and nonlocal-address acknowledgement groups are conditional. All values are demonstrations and are never applied.

For -accessible, the program intentionally uses **ANSI-free line prompts** rather than Huh's built-in accessible runner: in v2.0.3 the latter can emit ANSI styling and does not respect WithHideFunc in accessible mode. The plain path supports typing 'back' and 'quit', accepts piped input, and never activates raw terminal mode. Full-screen mode requires a TTY; -preview never requires interaction.

Manual input must be a canonical literal IPv4 address, not an IPv4-mapped IPv6 representation. Addresses outside RFC1918 and 100.64.0.0/10 require explicit acknowledgement. This is NOT firewall-rule validation; real installation will need stronger checks.

## Automated pseudo-terminal smoke

The experiment also runs a non-privileged Python-stdlib PTY check in CI
(`pty_smoke.py`). It starts the actual compiled full-screen wizard inside
80x24 and 60x20 terminals, waits for the Welcome page, sends Ctrl+C, and
asserts a clean zero-exit cancellation. This checks that the TUI can enter
and leave raw terminal mode without installing anything. It **does not**
replace manual keyboard navigation, terminal compatibility, SSH or
screen-reader acceptance tests on real machines.

## Dependency and CI policy

Both go.mod and go.sum are committed from a successful Go 1.25 resolution. CI uses 'go mod tidy -diff' and 'go mod verify' to detect drift, then runs tests, go vet, a build, and an ANSI-free accessible smoke test. Third-party license and supply-chain reviews remain open before release packaging.

## What to evaluate

- New/upgrade selections, Shift+Tab Back, cancel/quit, and conditional manual IP.
- Monitoring-only default and preservation of current power settings in upgrade mode.
- Narrow and monochrome terminals, SSH, screen readers and non-TTY fallback.
- Explicit warnings for nonlocal hub addresses without claiming reachability.
- Confirm that abort/preview never invoke sudo or access system state.

## Future work (out of scope)

Privileged/unprivileged controller API; root-owned verified payload staging; actual preflight and mDNS discovery; protected transaction-state inspection; crash recovery and health checks; config preservation and custom ports; SmartThings onboarding; then hardware and distribution acceptance.

The existing manual Linux installation remains unchanged and supported.
