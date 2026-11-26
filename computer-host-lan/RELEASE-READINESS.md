# Computer Host LAN — published rc.2 and stable release readiness

For v1.0.0-rc.3 qualification and exact-byte publication see [RC3-READINESS.md](docs/release/RC3-READINESS.md). The following rc.2 evidence is historical.

**Historical rc.2 prerelease:** [v1.0.0-rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2), published 2026-11-21 19:17:25 UTC from immutable commit `72e4a99c4b2e8f958ce771152826319318d0d537`. Linux/Edge **0.4.6-rc.2**, Windows **0.2.7-rc.2**, protocol v2. Four unsigned deliverables and `SHA256SUMS.txt` are available. **Do not replace these assets or move the tag.** [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) remains the last independently Windows 11 hardware-tested rollback baseline.

**Next candidate:** see the [rc.3 readiness and issue triage](docs/release/RC3-READINESS.md) for the post-#169 implementation freeze, outstanding decisions and physical acceptance record. This does not alter the published rc.2 evidence below.

## rc.2 publication verification

- [x] GitHub release and tag reference original rc.2 source commit `72e4a99c4b2e8f958ce771152826319318d0d537`; four unsigned deliverables and checksum manifest are present.
- [x] All four main-branch workflows passed on that SHA: [Linux 44933351339](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44933351339), [Windows 44933351147](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44933351147), [Inno 44933351273](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44933351273), [packaging 44933351260](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/44933351260).
- [x] Publisher reports Gentoo Linux rc.2 upgrade working normally with SmartThings (2026-11-21); individual rc.2 power cases and seven-day soak have not been documented.
- [ ] Independently compare downloaded public rc.2 assets to CI candidates, beyond the GitHub API digest and packaging CI evidence.
- [ ] Verify and record actual rc.2 channel-assigned and hub-installed Edge driver version; GitHub publication alone does not assign it.
- [ ] Complete Windows 11 rc.2 fresh-install/upgrade, GUI first paint, ACL/security handling, monitoring/power and recovery checks.
- [ ] Complete additional Linux physical platform testing and at least seven days of Windows/Linux unattended hub soak.
- [ ] Complete code-signing decision and final security/platform sign-off before stable v1.0.0. Third-party notice automation (#118) is a non-blocking follow-up; see the current rc.3 readiness record.

## Earlier beta evidence and historical follow-up

## Confirmed baseline (v0.5.5-beta.1)

- [x] Native Windows/Linux/build/package workflows passed on release SHA f7e2bccec348876ddfa40c3256b35b002a7cd3a8.
- [x] Windows 11 Pro tester: GUI in-place upgrade preserved settings and existing SmartThings device; accurate CPU/RAM/disk metrics, service stop/restart recovery (Off/Unreachable → On/Running), Wake/Restart/Sleep controls and working Wake-on-LAN; Windows agent 0.2.4-beta.1.
- [x] Gentoo Linux hydra with real SmartThings hub: discovery, telemetry, service recovery, reboot, suspend/WOL, shutdown/WOL and expanded RAM/root filesystem readings.

## Historical post-publication verification for v0.5.6

**Release engineering audit (2026-11-20):** [Verified tag, CI, published asset digests and open packaging/signing gates](docs/release/V1-RELEASE-ENGINEERING-AUDIT.md). The GitHub artifact-integrity checks below can now be distinguished from still-pending SmartThings deployment and hardware tests.

- [x] Verified all four workflows passed on release commit `ec0a88db25c30c988c2b26f01236fa8e56f968cd`; CI run links are recorded in the release engineering audit.
- [ ] Review abandoned installer snapshot recovery and service preservation, health-gated upgrade commits, UUID/key/configuration/custom-port retention and user-visible errors.
- [ ] Validate Windows policy-dependent privilege preflight, per-service SID/token ACL, virtual-NIC WOL selection, mDNS retries and failure recovery; do not weaken fail-closed behavior to make CI pass.
- [ ] Validate Linux atomic state creation and WOL configuration conflicts, and Edge slow shutdown/transient suspend state regressions.
- [x] Compared all four published GitHub asset SHA-256 digests plus `SHA256SUMS.txt` to the matching CI output/reconstructed checksum manifest; embedded source/Windows version and commit metadata were verified in packaging CI. See the audit for exact digests and method.
- [ ] Finish third-party redistribution notices and license sign-off from the resolved Windows build output; the present notices file is only an inventory.
- [ ] Independently exercise direct public-download links for each v0.5.6 asset and verify downloaded bytes (CI-to-GitHub asset digest checks are recorded above). Retain v0.5.5 as the tested fallback. Do not overwrite existing releases.
- [ ] Independently check Edge driver 0.4.4-beta.1 is assigned to the existing SmartThings channel 7a23289c-d1f8-42cc-ba10-4ffd219b89bb and installed on a hub, preserving driver 2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7 and existing devices.
- [ ] Complete a real Windows 11/Gentoo v0.5.6 test round; previous v0.5.5 hardware feedback does not validate these changes.

## Remaining gates before stable v1.0.0

The [stable release gates](docs/release/V1-RELEASE-GATES.md) remain in force. Public rc.2 is for testing; publication does **not** waive Windows/Linux hardware, security or soak requirements or applicable redistribution terms. Completion of #118 notice automation is not a release gate. The older rc.1 remains downloadable with its documented missing fixes.

- [ ] Retest Windows 11 rc.2 installer/upgrade, service recovery, WOL and power controls on real hardware.
- [ ] Record individual Linux rc.2 power/reconnection cases and test one physical Debian/Ubuntu system.
- [ ] Check relevant NIC/privilege policies/network profiles and safe recovery edge cases.
- [ ] Review signing and download integrity; SHA-256 validates bytes, not publisher identity. Track best-effort notice improvements separately in #118.
- [ ] Finish seven-day soak and retain trusted private LAN/unencrypted HTTP and hardware-specific sleep/WOL caveats.

No PR or CI workflow automatically publishes a GitHub release or assigns a SmartThings driver. Never purge persistent identities or keys to force a failed upgrade.
