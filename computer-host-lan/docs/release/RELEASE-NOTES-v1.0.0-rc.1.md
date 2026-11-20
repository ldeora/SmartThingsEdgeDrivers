# Computer Host LAN v1.0.0-rc.1 — release candidate

**Status:** RC source and assets prepared for CI and acceptance testing. GitHub publication and SmartThings driver deployment are separate steps; neither is implied by these notes. The [published v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) remains available, and v0.5.5-beta.1 is the hardware-tested rollback baseline.

**SmartThings channel:** [ARoedl SmartThings Edge Drivers](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) (same channel and Computer Host LAN driver ID; no new pairing).

| Component | RC version |
| --- | --- |
| Integration / GitHub asset version | **1.0.0-rc.1** |
| Linux host agent | **0.4.5-rc.1** |
| Windows host agent | **0.2.6-rc.1** |
| SmartThings Edge driver | **0.4.5-rc.1** |
| Local agent protocol | **v2 (unchanged)** |

## What's improved since the previous hardware-tested beta

- **Windows Setup:** Safer in-place upgrades with rollback snapshots, identity/version/health checks, preserved settings and clearer failure guidance.
- **Hub discovery and usability:** Improved first-page painting (PR #23) and retention of the selected hub's address when a retry temporarily finds nothing (PR #27). **The original Windows 11 rendering report still needs a real-hardware retest.**
- **Windows agent:** More resilient mDNS registration, shutdown-privilege checks with monitoring-only fallback, improved NIC selection for WOL and protected persistent state.
- **Linux and SmartThings:** More robust identity/WOL handling and cleaner delayed-shutdown/transient-suspend reporting; existing monitoring and device profiles stay compatible.
- **Release readiness:** Version-coherent RC packages and checksummed Windows Setup/ZIP, Linux source and documentation assets. No new pairing, rotation or power mechanism.

## Installation and upgrading

For first-time installations, see the [short RC quick start](QUICK-START.md). Windows 11 x64 should use the **unsigned graphical Setup.exe** after this RC is published; the ZIP/PowerShell method remains a fallback. Linux systems use the matching source ZIP. Always verify SHA-256 hashes, and use the trusted private LAN.

**Upgrades must preserve the existing SmartThings computer device, installation UUID, control key, configuration and power preference.** Do not uninstall or purge state before upgrading. Windows Setup validates the new agent and can restore an existing installation after detectable failures. Power operations remain **disabled by default** for new installations and depend on OS/NIC/firmware.

## What still needs physical verification

CI alone cannot verify pixel rendering or hub discovery on the reporting Windows machine, SmartThings channel assignment, hardware-specific WOL/sleep transitions, or multi-day stability. Before calling this candidate stable, verify Windows 11 upgrades and first-search layout on physical testers, Linux on a real hub, and continuity without duplicate SmartThings devices. Keep an existing known-good installer for recovery.

**No GitHub release, driver/channel assignment or physical tester installation is performed simply by merging the candidate PR.**
