# Computer Host LAN — v0.5.6-beta.1 release readiness

**Published prerelease:** [v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1) (Windows 0.2.5-beta.1; Linux/Edge 0.4.4-beta.1). **Hardware-tested baseline:** [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1); the v0.5.6 paths still require dedicated validation. Channel assignment and published artifact integrity are separate checks, not established by this file.

## Confirmed baseline (v0.5.5-beta.1)

- [x] Native Windows/Linux/build/package workflows passed on release SHA f7e2bccec348876ddfa40c3256b35b002a7cd3a8.
- [x] Windows 11 Pro tester: GUI in-place upgrade preserved settings and existing SmartThings device; accurate CPU/RAM/disk metrics, service stop/restart recovery (Off/Unreachable → On/Running), Wake/Restart/Sleep controls and working Wake-on-LAN; Windows agent 0.2.4-beta.1.
- [x] Gentoo Linux hydra with real SmartThings hub: discovery, telemetry, service recovery, reboot, suspend/WOL, shutdown/WOL and expanded RAM/root filesystem readings.

## Post-publication verification for v0.5.6

- [ ] Verify the four workflows were green on the exact published release commit (CI evidence must be recorded).
- [ ] Review abandoned installer snapshot recovery and service preservation, health-gated upgrade commits, UUID/key/configuration/custom-port retention and user-visible errors.
- [ ] Validate Windows policy-dependent privilege preflight, per-service SID/token ACL, virtual-NIC WOL selection, mDNS retries and failure recovery; do not weaken fail-closed behavior to make CI pass.
- [ ] Validate Linux atomic state creation and WOL configuration conflicts, and Edge slow shutdown/transient suspend state regressions.
- [ ] Recheck the published four unsigned release assets plus SHA256SUMS, matching source commit, component versions, and third-party notices.
- [ ] Confirm the published v0.5.6 GitHub prerelease assets have immutable versioned download paths; retain v0.5.5 assets as the tested fallback. Do not overwrite existing releases.
- [ ] Independently check Edge driver 0.4.4-beta.1 is assigned to the existing SmartThings channel 7a23289c-d1f8-42cc-ba10-4ffd219b89bb and installed on a hub, preserving driver 2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7 and existing devices.
- [ ] Complete a real Windows 11/Gentoo v0.5.6 test round; previous v0.5.5 hardware feedback does not validate these changes.

## Before v1.0.0-rc.1 or stable

- [ ] Retest installer upgrades, service recovery, WOL/Windows power controls and Linux state-machine changes on actual v0.5.6 hardware.
- [ ] Check additional NICs/privilege policies/Windows network profiles and recovery edge cases when practical.
- [ ] Review licenses and transitive dependency provenance; decide code signing/Authenticode policy. Checksums verify integrity, not publisher identity.
- [ ] Maintain the trusted-private-LAN, unsigned-beta, Windows S0/S3/S4/S5 and WOL limitations. Never promise power transitions are electrically confirmed.

No PR or CI workflow automatically publishes a GitHub release or assigns a SmartThings driver. Never purge persistent identities or keys to force a failed upgrade.
