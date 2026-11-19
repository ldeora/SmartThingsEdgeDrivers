# Computer Host LAN — stabilization / first stable-release candidate

**Published baseline:** v0.5.4-beta.1, GitHub prerelease (2026-11-19), from
`f19c114b1cca7dcb87b5774eff7602e70184047c`. All four release workflows
passed; ZIPs, Windows Setup.exe and unified SHA256SUMS are published.
Previous v0.5.3-beta.1 assets remain available.

**Current work:** draft [PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19)
on a dedicated branch. It has **not** been merged, deployed to a hub or
released, and must not be represented as a stable build.

## Verified evidence

- Linux Gentoo + physical SmartThings hub: discovery, telemetry, service
  recovery, Linux reboot/suspend/WOL/shutdown/WOL and four-value metrics.
- Native Windows Server 2025 CI: .NET service/contract, native Setup GUI
  navigation, install/upgrade/migration/uninstall; release packaging hashes.
- Real Windows 11 Pro tester, 2026-11-19: Setup installation and wizard upgrade
  succeeded; reported system statistics match expectations. Screenshot confirms
  Windows profile and CPU/RAM/disk UI. Earlier Windows tester reported native
  reboot/suspend/shutdown operations.
- No claim that all Windows NIC/power states or all Linux distributions are
  hardware-certified. Windows WOL and a full security penetration test remain open.

## Must pass before v1.0.0-rc.1

- [ ] All four CI workflows pass on **one exact PR head SHA** after code changes.
- [ ] Windows custom-port/config preservation and authentication-token ACL
      checks execute on a native runner (not merely source assertions).
- [ ] Windows interrupted graphical upgrade restores previous service and
      configuration. Test both explicit PowerShell error and premature abort.
- [ ] Verify the Lua suspend/cancelled-shutdown regressions in CI and hub
      observations; no optimistic electrical power claims.
- [ ] Test Windows 11 graphical install and upgrade on physical hardware again
      using the new candidate; test mDNS/manual-IP/Private-subnet fallback.
- [ ] Collect a second independent host/system combination when practical.
- [ ] Confirm Windows service stop/start, hub restart and WOL only on suitable
      physically recoverable test computers.
- [ ] Review complete licenses and transitive dependency notices in shipped
      Windows binaries; verify code copyright/provenance sign-off.
- [ ] Decide the release signing policy: unsigned builds must retain SmartScreen
      warnings; checksums do not authenticate publishers.
- [ ] Confirm no change to protocol v2 identity, SmartThings channel or
      registered capability schemas unless explicitly intended.
- [ ] Verify release source SHA, internal Windows agent version, source/ZIP/Setup
      hashes and published release assets. Then publish a **separate RC tag**.

**Release policy:** Keep v0.5.4-beta.1 intact until these gates are closed.
Never silently install a draft PR onto a user's computer. Treat any remaining
hardware-dependent limitation transparently instead of presenting it as a
universal guarantee.
