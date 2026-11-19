# Computer Host LAN — v0.5.5-beta.1 candidate publication gates

The **published** baseline is still [v0.5.4-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1). [PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19) was merged into `main` as `0978dd75557ce8b3b38693cdf740aaa2585ab0fa` and all four workflows passed on that commit. Those fixes are *not* present in published 0.5.4 binaries.

The candidate is **v0.5.5-beta.1** (Linux/Edge 0.4.3-beta.1, Windows 0.2.4-beta.1, protocol v2). The target [GitHub tag](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) is **not yet published**. The existing SmartThings channel is unchanged until an explicit new driver assignment.

## Publication checklist

- [ ] Merge versioned candidate sources and documentation after passing Linux, Windows agent, native Inno GUI and complete release-packaging CI.
- [ ] Use the **final merged `main` commit** and its release-candidate workflow, not preliminary PR assets. Verify 3 ZIPs, Windows Setup.exe and unified `SHA256SUMS.txt`, including `BUILD-INFO.json` source commit and runtime versions.
- [ ] Confirm rollback testing (including ZIP→Setup) and unchanged UUID, token, profile component IDs and protocol; document any hardware-limited behavior.
- [ ] Confirm third-party provenance/redistribution notices, unsigned SmartScreen wording and trusted-LAN restriction. Stable-release signing and full copyright sign-off are distinct, still-open gates.
- [ ] Publish an **additional** GitHub prerelease, targeting the candidate merged commit, without overwriting or retagging 0.5.4 or earlier versions.
- [ ] **Because the Edge driver changed**, package and assign Edge Driver 0.4.3-beta.1 to the existing SmartThings channel; do not create a replacement channel/driver identity.
- [ ] Verify published asset hashes, SmartThings app telemetry/profile after updating the driver and safely upgrade Windows 11/Gentoo test devices.
- [ ] Then publish the prepared Community update; retain v0.5.4 for rollback.

No workflow automatically publishes a release or deploys a SmartThings driver. Full first-stable-release gates are tracked in [RELEASE-READINESS.md](../../RELEASE-READINESS.md).
