# Computer Host LAN — v0.5.6-beta.1 post-publication verification

**Published prerelease:** [v0.5.6-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1), dated 2026-11-20. **Previously hardware-tested baseline:** [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). The existence of a GitHub release does not demonstrate that the matching Edge driver was assigned or that the new runtime/installer behaviors passed real-hardware tests.

## Verify the published beta

- [ ] Record final merged release commit and verify all four CI workflows for that exact commit.
- [ ] Independently check the four public deliverables (3 ZIP files and Windows Setup.exe) plus SHA256SUMS, internal BUILD-INFO, component versions, and source SHA. Never replace the published tag/assets to fix a failed check; publish a corrective version instead.
- [ ] Confirm the existing SmartThings channel `7a23289c-d1f8-42cc-ba10-4ffd219b89bb` has Edge driver 0.4.4-beta.1 installed on at least one test hub, preserving driver ID `2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7`.
- [ ] Complete v0.5.6 Windows 11 and Gentoo hardware checks for upgrade recovery, identity/key preservation, service resilience, selected physical WOL NIC, and state-machine recovery. Mark destructive failure simulations as controlled tests only.
- [ ] Review third-party redistribution/provenance notices, unsigned SmartScreen guidance, and trusted-LAN restrictions.
- [ ] After confirming the driver is available and the instructions match published binaries, update the SmartThings Community thread. Do not claim physical validation until reported.
- [ ] Preserve the v0.5.5 release and already-paired SmartThings devices. Never delete persistent UUIDs or control tokens to force a successful upgrade.

## Stable v1.0 readiness

Hardware coverage, soak tests, security/third-party sign-off, and explicit Windows code-signing policy remain separate release gates. See [RELEASE-READINESS.md](../../RELEASE-READINESS.md) and the [v0.5.6 tester checklist](TESTER-CHECKLIST.md).

No workflow automatically publishes a GitHub release or deploys a SmartThings driver.
