# Computer Host LAN — SmartThings for Linux and Windows

**Development version: v0.5.1-dev.1** · Shared SmartThings Edge Driver v0.4.0-dev.1 · Linux agent v0.4.0-dev.1 · Windows agent v0.2.0-alpha.1 · Protocol v2.

Computer Host LAN is a **separate** project from [Linux Host LAN](../linux-host-lan/). It uses the `_computerhost._tcp` discovery service and `/v2` HTTP API. **Do not pair a protocol-v1 Linux Host LAN agent with this driver.**

## What has actually been tested?

| Target | Evidence |
| --- | --- |
| Linux / Gentoo on `hydra` | SmartThings hub hardware: discovery, monitoring, agent loss/recovery, reboot, suspend/WOL and shutdown/WOL passed on 2026-11-16 |
| Linux / Debian 12–13, Ubuntu 24.04–26.04, Fedora 43–44 | Source/container tests passed in CI; no physical power/state certification |
| Windows x64 | .NET 10 build, protocol/security tests, HTTP smoke, installation as `NT AUTHORITY\LocalService` and opt-in/opt-out tested on Windows Server 2025 runner ([CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333)) |
| Windows ARM64 | Cross-publish passed; not executed on ARM64 hardware |
| Windows 11 with a SmartThings hub | **Not yet physically validated**; the public beta is intended to recruit volunteers for this |

Windows system metrics include CPU, RAM, system-drive usage and uptime. CPU temperature and Linux load averages are not invented on Windows. Shutdown/reboot/suspend are opt-in, best-effort and HMAC-authenticated. WOL is sent by the hub and depends on the NIC, firmware, network topology and Windows power state.

## Documentation

- [Installation (both platforms)](INSTALLATION.md)
- [Beta tester onboarding](docs/beta/START-HERE.md)
- [Tester checklist](docs/beta/TESTER-CHECKLIST.md)
- [Feedback and privacy](docs/beta/FEEDBACK-AND-SUPPORT.md)
- [Supported / unverified environments](docs/beta/COMPATIBILITY-STATUS.md)
- [Protocol v2](PROTOCOL.md)
- [Security limitations](docs/beta/SECURITY-AND-PRIVACY.md)
- [Release gates](docs/beta/PUBLICATION-GATES.md)

**Do not distribute this development branch as a finished public beta.** The SmartThings beta channel invitation, immutable versioned GitHub Release assets, first Windows 11 LAN discovery and the release support process are pending. The historical Linux v0.3.1 material lives in `docs/history/v0.3.1-beta.1/`. Existing Linux Host LAN devices remain on the separate legacy project.
