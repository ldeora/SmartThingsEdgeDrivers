# Computer Host LAN — SmartThings for Linux and Windows

**Latest published prerelease: [v1.0.0-rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2)** (November 21, 2026 UTC, immutable source commit `72e4a99c4b2e8f958ce771152826319318d0d537`). Linux/Edge **0.4.6-rc.2**, Windows agent **0.2.7-rc.2**, protocol **v2 unchanged**. Obtain version-matched unsigned Windows Setup/ZIP or Linux source and checksums from the release rather than CI artifacts. [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) remains the last independently Windows 11 hardware-tested rollback baseline; rc.2 Windows 11 acceptance remains pending.

**Development source is not the published rc.2 package.** The legacy
Linux mutating source entry points are retired in main. Use the published
version-matched release for rc.2 instructions; do not elevate a main
checkout or development source archive. The future authenticated Linux
wizard/CLI still requires release qualification.

## Published rc.2 versus older rc.1

The [older rc.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) was built from tag `5466ad0`. Published rc.2 adds PRs #56–#60: HTTP timeouts/header deadlines, power acknowledgments, hardened Windows ProgramData state, discovery/Wake recovery and publication guidance. See the [rc.2 notes](docs/release/RELEASE-NOTES-v1.0.0-rc.2.md) and [installation guide](INSTALLATION.md#known-differences-between-rc1-and-rc2). Passing CI is not physical Windows 11 acceptance.

**Historical rc.1 security caution:** rc.1 lacks PR #58's retained-state and credential protections ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)). Do not enable rc.1 authenticated power on a shared PC with untrusted local users; checking ProgramData once does not eliminate its fresh-install race. Prefer published rc.2 and preserve existing UUIDs/keys. See [rc.1 security limitations](SECURITY.md#known-issues-in-the-published-rc1).

Computer Host LAN is a **separate** project from [Linux Host LAN](../linux-host-lan/). It uses the `_computerhost._tcp` discovery service and `/v2` HTTP API. **Do not pair a protocol-v1 Linux Host LAN agent with this driver.**

## What has actually been tested?

| Target | Evidence |
| --- | --- |
| Linux / Gentoo on `hydra` | Real hub: discovery, monitoring, recovery, reboot, suspend/WOL and shutdown/WOL; on 2026-11-18 verified the RAM/filesystem values; the publisher reports an rc.2 Linux upgrade working as expected (2026-11-21), without individually documented rc.2 power/soak results |
| Linux / Debian 12–13, Ubuntu 24.04–26.04, Fedora 43–44 | Source/container tests passed in CI; no physical power/state certification |
| Windows x64 | .NET 10 build, protocol/security tests, HTTP smoke, installation as `NT AUTHORITY\LocalService` and opt-in/opt-out tested on Windows Server 2025 runner ([CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333)) |
| Windows ARM64 | Cross-publish passed; not executed on ARM64 hardware |
| Windows 11 with a SmartThings hub | Public-beta tester reports successful **graphical Setup installation and upgrade** on Windows 11 Pro; screenshot shows CPU, memory and system-drive telemetry correctly displayed. A v0.5.5 Windows 11 tester also confirmed correct service recovery, Wake/Restart/Sleep controls and working Wake-on-LAN. The rc.2 Windows-specific changes still require physical Windows 11 acceptance. |

Windows system metrics include CPU, RAM, system-drive usage and uptime. Both agents now report **Usage %, Total GiB, Used GiB, Available GiB** for RAM and their root/system filesystem. The new byte fields are optional protocol-v2 additions; old agents remain supported. On Linux, reserved filesystem blocks mean Used + Available may differ from Total. CPU temperature and Linux load averages are not invented on Windows. Shutdown/reboot/suspend are opt-in, best-effort and HMAC-authenticated. WOL is sent by the hub and depends on the NIC, firmware, network topology and Windows power state.

## Documentation

- [Installation (both platforms)](INSTALLATION.md)
- [v1.0 RC quick start](docs/release/QUICK-START.md)
- [Published rc.2 release notes](docs/release/RELEASE-NOTES-v1.0.0-rc.2.md)
- [Published rc.1 release notes (historical)](docs/release/RELEASE-NOTES-v1.0.0-rc.1.md)
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

**Release status:** [rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2) is published from immutable commit `72e4a99c4b2e8f958ce771152826319318d0d537`. The tag and four release assets plus checksum manifest remain unchanged by this documentation PR. GitHub publication does **not** prove SmartThings channel assignment or hub installation, which must be verified separately. Windows 11 hardware tests, further Linux checks and seven-day soak remain open; do not delete/re-pair existing devices during upgrades.
