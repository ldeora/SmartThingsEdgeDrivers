> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# Linux Host LAN — release engineering decision brief

Date: 2026-11-15 | Source bundle: v0.2.11 | **Not publicly released**

## Proven so far

A live Gentoo host with SmartThings has passed:
- IPv4/mDNS discovery, stable UUID, polling, CPU temperature + CPU/RAM/disk/load/uptime metrics;
- connected ↔ agent-unreachable ↔ connected without false Switch Off;
- authenticated reboot and suspend, WOL wake after suspend;
- authenticated graceful shutdown, Switch Off inference, WOL power-on and state recovery;
- English/German capability presentation registration on the developer account.

Other distributions have **not** yet been installed or tested, and a live
network outage remains untested. WOL and CPU temperature are hardware-dependent.

## Host-specific audit

No private hostname, address or MAC is embedded in the production agent or
Edge logic. The current release bundle replaces those identifiers in tests and
documentation with example values. The namespace `oceancircle09600` remains
hardcoded intentionally because it is the **publisher's** custom capability
namespace. Public users will use the publisher-provided Edge channel and
capabilities; they must not register their own capabilities.

## Packaging decision

Prefer one offline, auditable installer for controlled technical beta while
validating installation behavior. Add native DEB and RPM packages for broader
public release once disposable virtual machines verify their dependency,
service ownership, rollback and purge semantics. A generated package that has
not been installed and upgraded on its target distro is not a tested package.
Keep the **same agent source** across native and manual distribution; keep
persistent identity/key paths stable.

## Distribution priorities

P0: Debian 12/13, Ubuntu 22.04/24.04/26.04 LTS, Fedora 43/44.
P1: RHEL-compatible 9/10, Arch Linux, openSUSE 16.
P2: additional ARM64/Raspberry Pi hardware.
RHEL 9 requires an explicitly selected Python >=3.10 rather than its default
Python 3.9. WOL persistence depends on the active network manager; do not
assume a distro's backend. SELinux must be tested in enforcing mode.

## Changes in v0.2.11

- Adds `scripts/preflight.sh` (read only, does not require root).
- `install-agent.sh` now checks that Python is >=3.10 **before** mutating files,
  searches for compatible parallel installations and accepts `--python PATH`.
- Adds the distribution matrix, security review, package strategy, beta
  milestones and sanitized fixtures.
- No changes to agent v0.2.2, Edge driver v0.2.9, runtime status/power control.

## Explicit no-go items before unrestricted public beta

1. HTTP listener abuse/resource exhaustion and nonce issuing/eviction behavior.
2. Shared HMAC key storage in SmartThings preferences, recovery and rotation.
3. Authenticated root-helper acknowledgement/execution behavior and negative tests.
4. Fresh installation + in-place upgrades + removal on non-Gentoo Linux VMs.
5. SELinux enforcing and desktop/server firewall + mDNS discovery behavior.
6. Channel onboarding UX, complete English/German manuals, license, support and
   issue-reporting policy, tagged/checksummed reproducible releases.

## Source URLs and detailed material

See `DISTRO-MATRIX.md`, `PACKAGING-STRATEGY.md`,
`SECURITY-REVIEW-RELEASE.md`, `RELEASE-PLAN.md` and `README.md`.
Research is based on official distribution/systemd/Python docs linked there.
