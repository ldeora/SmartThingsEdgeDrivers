# Computer Host LAN — release history

## v1.0.0-rc.3 — published 2026-11-27 UTC

[Published release notes](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3) · [Qualification record](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/119)

- Linux: standalone protected x64 installer, full-screen and accessible
  wizard, CLI, explicit retained-state reuse, local historical restore,
  journaled recovery/uninstall and persistent wired WOL with owned removal.
- Windows: preserve validated power preference and firewall scope on upgrade,
  improved private-state checks, DNS-SD retries, service description and Setup UX.
- Edge: faster command acknowledgements without optimistic completion,
  conservative shutdown grace, persistent inferred Stopped/Suspended,
  bounded HTTP deadlines, safer endpoint selection and per-source limits.
- SmartThings: Host Status tile with switch action and retained capabilities
  and routines. Account-level presentation updates remain separate.
- Linux reproducible builds, exact build metadata and third-party notices;
  unsigned distribution. Protocol v2 unchanged.

Known limitations and exact published package names are in the release notes.
Use the published versioned assets; documentation improvements on main
do not modify those assets.

## v1.0.0-rc.2 — 2026-11-21

HTTP timeout enforcement and Linux header deadline; Windows protected
ProgramData ACL/ownership and graceful power acceptance; failed discovery
and Wake handling; Private-network warnings and recovery improvements.
[Tagged documentation](https://github.com/ldeora/SmartThingsEdgeDrivers/tree/computer-host-lan-v1.0.0-rc.2/computer-host-lan).

## v1.0.0-rc.1 — 2026-11-20

Release candidate installation/upgrade readiness and cross-platform
packaging. Later security fixes are not in rc.1: see
[rc.1 security notice](SECURITY.md#known-issues-in-the-published-rc1).
[Tagged documentation](https://github.com/ldeora/SmartThingsEdgeDrivers/tree/computer-host-lan-v1.0.0-rc.1/computer-host-lan).

## v0.5.x betas

- v0.5.6: upgrade recovery, discovery, credentials and power-state hardening.
- v0.5.5: Windows GUI and service stabilization, preserved settings,
  firewall scope maintenance and upgrade recovery.
- v0.5.4: native graphical Windows installer.
- v0.5.3: four RAM/filesystem readings (percentage, total, used, available).
- v0.5.2: root/system filesystem capacity.
- v0.5.1: first public cross-platform beta with Windows service and
  authenticated optional power, Linux agent and SmartThings Edge driver.

## Earlier releases

Protocol v2 replaced the Linux-only v1 contract; these identities are
separate. Full historical change log and documents are retained in
[the pre-cleanup Git snapshot](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/ae6a53d870df67a1e3756a06ed9857731d8ba8a5/computer-host-lan/CHANGELOG.md),
[release tags](https://github.com/ldeora/SmartThingsEdgeDrivers/releases)
and [the earlier Linux-only history](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/ae6a53d870df67a1e3756a06ed9857731d8ba8a5/computer-host-lan/docs/history/v0.3.1-beta.1/CHANGELOG.md).
