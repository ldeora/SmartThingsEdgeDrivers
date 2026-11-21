# Computer Host LAN — SmartThings for Linux and Windows

**Current source candidate (NOT published): v1.0.0-rc.2.** The matching components are Linux agent and Edge driver **0.4.6-rc.2**, Windows agent **0.2.7-rc.2**, protocol **v2 unchanged**. This version is prepared for source/CI review; **there is no rc.2 GitHub release, new tag or automatic SmartThings channel assignment yet.** Do not install temporary CI artifacts as if they were a published release. The latest published prerelease is [v1.0.0-rc.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) (November 20, 2026, UTC). [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) remains the independently hardware-tested Windows rollback baseline.

## rc.2 candidate versus published rc.1

**The downloadable rc.1 installers and agents were built from tag `5466ad0` and do not contain the subsequent fixes.** The rc.2 source candidate contains PRs #56–#60, including HTTP reliability, power acknowledgment improvements, **Windows ProgramData ownership and atomic state creation**, discovery/Wake behavior and release metadata/documentation corrections. See the [rc.2 release notes](docs/release/RELEASE-NOTES-v1.0.0-rc.2.md) and [installation instructions](INSTALLATION.md#known-differences-between-rc1-and-main). CI success is not physical acceptance of this candidate.

**Security caution for published rc.1:** the Windows installer in rc.1 still lacks PR #58's retained-state/credential hardening ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)). Do not enable rc.1 authenticated power commands on a shared PC with untrusted local accounts; checking the ProgramData directory once does not eliminate its fresh-install race. Keep existing installation IDs and control keys intact during upgrades. The [security page](SECURITY.md#known-issues-in-the-published-rc1) documents rc.1 limitations separately.

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
- [v1.0 RC quick start](docs/release/QUICK-START.md)
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

**Release status:** The [v1.0.0-rc.1 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) is published, with unsigned Windows x64 Setup.exe and ZIP, Linux source, documentation and checksums. Do not distribute temporary CI/PR artifacts as installers. Prefer the graphical Setup.exe for Windows x64; ZIP/PowerShell remains a fallback. The existing SmartThings channel must be checked separately for the matching Edge driver before hub upgrades. Publication does not establish real-hardware validation of this RC, and no re-pairing or new channel is intended.
