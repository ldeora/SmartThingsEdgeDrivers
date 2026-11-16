# Computer Host LAN — change log

## v0.5.1-dev.1 (2026-11-16) — cross-platform CI candidate

- Retains the Linux v0.4.0-dev.1 reference agent and its hardware-validated SmartThings Edge Driver behavior.
- Native Windows Host Agent v0.2.0-alpha.1 provides CPU/RAM/drive/uptime telemetry, Windows Service and DNS-SD registration, opt-in HMAC-authenticated reboot/shutdown/suspend and candidate WOL metadata.
- Windows Server 2025 x64 CI verified compilation, self-contained publishing, protocol/HMAC tests, HTTP smoke, LocalService installation, protected state, and PowerShell 5.1 opt-in/out. Real Windows 11 SmartThings and hardware power behavior remain **unverified**.
- Windows ARM64 cross-publish verified; runtime untested.
- Separate `computer-host-lan/` project directory; independent `linux-host-lan/` retained.
- Follow-up repository cleanup updates active CI workflows, versioned source-manifest generation, current beta guidance and issue reporting. No Windows or Linux runtime changes in that cleanup.
- Not yet a released public-beta version. No SmartThings channel invitation or permanent GitHub release assets yet.

## v0.5.0-dev.1 (2026-11-16) — Windows monitoring source

Initial Windows monitoring agent implementation and test scaffolding.

## v0.4.0-dev.1 (2026-11-16) — generic protocol v2

New `_computerhost._tcp` discovery, `computer-host-agent` API v2, shared driver, platform-specific profiles and custom monitoring capabilities. Linux successfully validated on Gentoo `hydra`.

Older Linux-only release history: [archived change log](docs/history/v0.3.1-beta.1/CHANGELOG.md).
