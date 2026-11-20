# Computer Host LAN — SmartThings for Linux and Windows

**In preparation:** v1.0.0-rc.1 (Windows agent **0.2.6-rc.1**; Linux agent/Edge driver **0.4.5-rc.1**; protocol v2 unchanged). **Not yet published or deployed.** [v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) is the latest published beta; [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) is the independently hardware-tested fallback. The RC still needs physical Windows and Linux validation.

Computer Host LAN is a **separate** project from [Linux Host LAN](../linux-host-lan/). It uses the `_computerhost._tcp` discovery service and `/v2` HTTP API. **Do not pair a protocol-v1 Linux Host LAN agent with this driver.**

## What has actually been tested?

| Target | Evidence |
| --- | --- |
| Linux / Gentoo on `hydra` | Real hub: discovery, monitoring, recovery, reboot, suspend/WOL and shutdown/WOL; on 2026-11-18 verified all four RAM and root filesystem values with the German SmartThings detail view and raw agent metrics |
| Linux / Debian 12–13, Ubuntu 24.04–26.04, Fedora 43–44 | Source/container tests passed in CI; no physical power/state certification |
| Windows x64 | .NET 10 build, protocol/security tests, HTTP smoke, installation as `NT AUTHORITY\LocalService` and opt-in/opt-out tested on Windows Server 2025 runner ([CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333)) |
| Windows ARM64 | Cross-publish passed; not executed on ARM64 hardware |
| Windows 11 with a SmartThings hub | Public-beta tester reports successful **graphical Setup installation and upgrade** on Windows 11 Pro; screenshot shows CPU, memory and system-drive telemetry correctly displayed. A v0.5.5 Windows 11 tester also confirmed correct service recovery, Wake/Restart/Sleep controls and working Wake-on-LAN. The v0.5.6 changes still need validation. |

Windows system metrics include CPU, RAM, system-drive usage and uptime. Both agents now report **Usage %, Total GiB, Used GiB, Available GiB** for RAM and their root/system filesystem. The new byte fields are optional protocol-v2 additions; old agents remain supported. On Linux, reserved filesystem blocks mean Used + Available may differ from Total. CPU temperature and Linux load averages are not invented on Windows. Shutdown/reboot/suspend are opt-in, best-effort and HMAC-authenticated. WOL is sent by the hub and depends on the NIC, firmware, network topology and Windows power state.

## Documentation

- [Installation (both platforms)](INSTALLATION.md)
- [v1.0 RC quick start (for when the RC is published)](docs/release/QUICK-START.md)
- [RC release notes](docs/release/RELEASE-NOTES-v1.0.0-rc.1.md)
- [Previously published beta guide](docs/beta/START-HERE.md)
- [Tester checklist](docs/beta/TESTER-CHECKLIST.md)
- [Feedback and privacy](docs/beta/FEEDBACK-AND-SUPPORT.md)
- [Supported / unverified environments](docs/beta/COMPATIBILITY-STATUS.md)
- [Protocol v2](PROTOCOL.md)
- [Security and responsible use](SECURITY.md)
- [Short beta security and privacy guidance](docs/beta/SECURITY-AND-PRIVACY.md)
- [Release gates](docs/beta/PUBLICATION-GATES.md)
- [First stable release acceptance gates](docs/release/V1-RELEASE-GATES.md)

**SmartThings installation:** [ARoedl SmartThings Edge Drivers](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). Enroll the existing hub and install the Computer Host LAN driver; do not re-pair existing computer devices during upgrades.

**Release status:** The v1.0.0-rc.1 source tree is a candidate, not a published download. Do not distribute temporary CI/PR artifacts as stable installers. After the RC is approved and published, prefer the unsigned Windows x64 Setup.exe; ZIP/PowerShell remains a fallback. The existing SmartThings channel must be checked separately for the matching RC driver before testers upgrade their hubs. No re-pairing or new channel is intended.
