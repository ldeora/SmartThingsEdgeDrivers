# Computer Host LAN — v0.5.5-beta.1 stabilization and first stable-release candidate

**Published baseline:** v0.5.4-beta.1, GitHub prerelease (2026-11-19), from
`f19c114b1cca7dcb87b5774eff7602e70184047c`. All four release workflows
passed; ZIPs, Windows Setup.exe and unified SHA256SUMS are published.
Previous v0.5.3-beta.1 assets remain available.

**Stabilization implemented and merged:** [PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19), main commit `0978dd75557ce8b3b38693cdf740aaa2585ab0fa`, four workflows passed. **Next:** candidate v0.5.5-beta.1 with bumped components. This version has **not been published or deployed to a SmartThings channel**. It is not a stable build.

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

- [x] All four CI workflows passed on the merged PR #19 `main` SHA (`0978dd75557ce8b3b38693cdf740aaa2585ab0fa`).
- [ ] All four CI workflows must also pass on **one exact v0.5.5-beta.1 candidate `main` SHA** after versioning and release docs.
- [x] Windows custom-port/config preservation and authentication-token ACL checks executed on native Windows CI for PR #19.
- [ ] Verify these checks again on the exact versioned beta candidate commit.
- [x] CI simulated a detected upgrade failure and verified recovery of configuration and running service.
- [ ] Physical interrupted/aborted Setup recovery remains to be verified, including unexpected termination.
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

## Beta publication (separate from stable v1.0 gates)

- [ ] Merge v0.5.5-beta.1 release/version PR and confirm green CI on **final `main` commit**, not an earlier PR build.
- [ ] Verify all four asset names, exact source SHA in Windows `BUILD-INFO.json`, self-reported component versions, and unified `SHA256SUMS.txt`.
- [ ] Publish a **new prerelease** `computer-host-lan-v0.5.5-beta.1`; preserve v0.5.4 assets for rollback. Windows Setup and ZIP remain unsigned.
- [ ] Repackage/assign Edge driver v0.4.3-beta.1 into the existing SmartThings channel, preserving driver ID, profiles and registered capability schemas; verify installed beta device.
- [ ] Ask Windows 11 Pro tester to validate v0.5.4 → v0.5.5 graphical in-place upgrade, token/UUID/settings, metrics, service recovery, and errors; Linux Gentoo recheck.
- [ ] Only after artifacts and driver are ready, announce the new beta in the Community thread. Stable-release signing and full copyright/legal review remain open.
