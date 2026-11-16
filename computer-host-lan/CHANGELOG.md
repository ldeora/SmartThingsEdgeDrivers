# Change log — Phase 2

## 0.5.0-dev.1 (2026-11-16) — Windows monitoring alpha source

- Added C#/.NET 10 native Windows Host Agent source, system metrics,
  boot-session tracking, persistent UUID, read-only v2 HTTP API and native DNS-SD.
- Added Windows Service install/uninstall scripts, self-contained publish
  recipe, console contract tests, Windows CI build and HTTP smoke definition.
- Updated Windows SmartThings profile to be monitoring-only (no power buttons
  or unsupported CPU temperature); **Linux profile and driver logic unchanged**.
- Linux v0.4.0-dev.1 independently validated on Gentoo `hydra`: monitoring,
  mDNS, agent restart/recovery, reboot, suspend/WOL, full shutdown/WOL.
- Windows agent has not been compiled/executed on real Windows in this
  environment; do not present as an installable signed release.

# Changelog

## 0.4.0-dev.1 — 2026-11-16 — cross-platform source refactor (NOT verified on hub)

- Renamed SmartThings driver from Linux Host LAN to Computer Host LAN, with
  `computer-host-lan` package key, `computerhost` Lua modules, and new device
  network IDs. No in-place device or automation migration is attempted.
- Introduced generic agent protocol `computer-host-agent` v2 with `/v2/*`,
  mandatory `platform`, generic HMAC request headers, and DNS-SD
  `_computerhost._tcp`.
- Added Linux/Windows SmartThings profiles; kept Linux-specific `linuxLoad`
  and all formerly available Linux metrics, state-machine operations and
  power controls. No Windows agent is included at this stage.
- Added five platform-independent custom capabilities in the existing account
  namespace; new capability registration is required for the updated profiles.
- Retained Linux systemd service, privileged helper, installer, WOL scripts,
  protective resource limits, persistent state and opt-in controls.
- Added generic contract, platform selection and Linux parity tests.
- Source tests and loopback tests pass; actual hub/hardware validation pending.

See `docs/history/v0.3.1-beta.1/CHANGELOG.md` for the original version history.
