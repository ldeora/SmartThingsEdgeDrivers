# Computer Host LAN — SmartThings for Linux and Windows

**Next beta candidate: v0.5.4-beta.1** · SmartThings Edge Driver v0.4.2-beta.1 · Linux agent v0.4.2-beta.1 · Windows agent v0.2.3-beta.1 · Protocol v2 unchanged.

Computer Host LAN is a **separate** project from [Linux Host LAN](../linux-host-lan/). It uses the `_computerhost._tcp` discovery service and `/v2` HTTP API. **Do not pair a protocol-v1 Linux Host LAN agent with this driver.**

## What has actually been tested?

| Target | Evidence |
| --- | --- |
| Linux / Gentoo on `hydra` | Real hub: discovery, monitoring, recovery, reboot, suspend/WOL and shutdown/WOL; on 2026-11-18 verified all four RAM and root filesystem values with the German SmartThings detail view and raw agent metrics |
| Linux / Debian 12–13, Ubuntu 24.04–26.04, Fedora 43–44 | Source/container tests passed in CI; no physical power/state certification |
| Windows x64 | .NET 10 build, protocol/security tests, HTTP smoke, installation as `NT AUTHORITY\LocalService` and opt-in/opt-out tested on Windows Server 2025 runner ([CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333)) |
| Windows ARM64 | Cross-publish passed; not executed on ARM64 hardware |
| Windows 11 with a SmartThings hub | **First beta tester reports successful installation and basic operation, plus Suspend, Reboot and Shutdown (Off)**; detailed monitoring and Windows WOL remain unverified |

Windows system metrics include CPU, RAM, system-drive usage and uptime. Both agents now report **Usage %, Total GiB, Used GiB, Available GiB** for RAM and their root/system filesystem. The new byte fields are optional protocol-v2 additions; old agents remain supported. On Linux, reserved filesystem blocks mean Used + Available may differ from Total. CPU temperature and Linux load averages are not invented on Windows. Shutdown/reboot/suspend are opt-in, best-effort and HMAC-authenticated. WOL is sent by the hub and depends on the NIC, firmware, network topology and Windows power state.

## Documentation

- [Installation (both platforms)](INSTALLATION.md)
- [Beta tester onboarding](docs/beta/START-HERE.md)
- [Tester checklist](docs/beta/TESTER-CHECKLIST.md)
- [Feedback and privacy](docs/beta/FEEDBACK-AND-SUPPORT.md)
- [Supported / unverified environments](docs/beta/COMPATIBILITY-STATUS.md)
- [Protocol v2](PROTOCOL.md)
- [Security limitations](docs/beta/SECURITY-AND-PRIVACY.md)
- [Release gates](docs/beta/PUBLICATION-GATES.md)

**Release plan:** v0.5.4-beta.1 brings the graphical Windows Setup.exe into the public beta as the recommended Windows installation and upgrade method; the existing ZIP/PowerShell route remains supported. See [installation](INSTALLATION.md) and [Setup details](windows-agent/installer/README.md). Linux and the SmartThings Edge driver are unchanged from v0.5.3-beta.1, and existing devices do not need re-pairing.

**Current public download:** [v0.5.3-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1); the [v0.5.4-beta.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1) is available only after its prerelease is published. The [SmartThings driver channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) is unchanged. Windows 11 hub discovery, network edge cases and WOL remain beta test objectives.
