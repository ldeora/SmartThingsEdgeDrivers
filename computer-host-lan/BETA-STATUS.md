# Computer Host LAN — next beta candidate v0.5.5-beta.1 (2026-11-19)

**Candidate awaiting publication:** integration v0.5.5-beta.1 (Linux agent / Edge driver v0.4.3-beta.1; Windows agent v0.2.4-beta.1), based on merged PR #19 and new versioning PR. The source code includes the new safeguards, but no v0.5.5 files are yet published. Candidate notes: [v0.5.5-beta.1](docs/beta/RELEASE-NOTES-v0.5.5-beta.1.md). Protocol v2, installation UUIDs, control keys and the existing channel remain compatible.

**Publishing gate:** merge and rerun all four CI workflows at the final commit, verify asset hashes and source metadata, confirm the Edge driver is packaged and assigned to the existing SmartThings channel, and separately publish a new GitHub prerelease before inviting testers to upgrade. Do not modify older release assets. Third-party licensing and signing require publisher review before stable v1.0.

## Published baseline: v0.5.4-beta.1

**Current public download:** [v0.5.4-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1), published November 19 from commit `f19c114b1cca7dcb87b5774eff7602e70184047c`.
The Linux agent and Edge Driver remain v0.4.2-beta.1; Windows agent
v0.2.3-beta.1; protocol v2 and the existing shared SmartThings channel are
unchanged. Both Windows Setup.exe and ZIP/PowerShell remain supported.

**Hardware confirmation:** A Windows 11 Pro volunteer has now reported
successful installation and upgrade through the actual graphical wizard,
accurate CPU/RAM/disk monitoring, and provided a SmartThings screenshot.
The previous Windows volunteer's report confirmed suspend, reboot and
shutdown actions. This is valuable real-hardware evidence, not complete
coverage of WOL, every firmware or network recovery scenario.

**Stabilization merged:** [PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19) now resides in `main` (`0978dd75557ce8b3b38693cdf740aaa2585ab0fa`), with all four workflows passing. Its changes are **not** in the published v0.5.4-beta.1 binaries. They will first be distributed in the separately published v0.5.5-beta.1.
The first stable release candidate is gated by
[release readiness](RELEASE-READINESS.md), including actual Windows hardware
retests and publisher licensing/provenance sign-off. Preserve the published
v0.5.4-beta.1 assets for rollback.


---

# Next candidate: Computer Host LAN v0.5.3-beta.1 — preparing publication

PR #15 merged 2026-11-18. Real Gentoo Linux `hydra` + SmartThings hub confirmed eight RAM/root filesystem readings in the German app and `devices:status`. The new agent fields are present in `/v2/metrics`; account-level custom-capability schema/translations/presentations have already been updated by the owner. One German translation upsert initially returned HTTP 422 but succeeded on retry. No device re-pairing was required.

**Version plan:** Linux agent and Edge Driver 0.4.2-beta.1; Windows agent 0.2.2-beta.1; protocol v2 unchanged. Windows Server CI passed PR #15 including new Windows metrics and service tests, but Windows 11 hardware confirmation of the new four values is still needed. Publish only after final release-commit CI and SHA-256 verification; update the **existing** SmartThings channel with the same driver ID. The prior [v0.5.2-beta.1 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.2-beta.1) stays available for rollback, with no replacement of old assets.

---

# Previous public beta: v0.5.2-beta.1 (2026-11-18)

Integration 0.5.2-beta.1, Linux agent/Edge Driver 0.4.1-beta.1 and Windows agent 0.2.1-beta.1 were released with total root/system filesystem capacity in GiB. New channel driver was assigned and GitHub release published on 2026-11-18.

---

# Computer Host LAN — public beta v0.5.1-beta.1

**Integration:** 0.5.1-beta.1. Linux agent and Edge Driver: 0.4.0-dev.1. Windows agent: 0.2.0-alpha.1. Protocol: v2.

**Published beta baseline:** [GitHub prerelease v0.5.1-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) was published from commit `1155620c83247c3820f6fd4b7d52d568e86740c0`. The released assets and the installed Edge Driver are **not changed** by subsequent documentation or experimental branches.

**Linux reference hardware:** Gentoo Linux `hydra` with a real SmartThings hub passed discovery, telemetry, agent loss/recovery, reboot, suspend/WOL, and shutdown/WOL.

**Windows 11 early volunteer feedback (reported 2026-11-16/17):** A public-beta tester reports successful installation and basic SmartThings operation on a Windows 11 system. The tester initially could not paste the 64-character control key using the usual Android Paste menu, but successfully entered it through the keyboard clipboard. The same tester subsequently confirmed **Suspend**, **Reboot**, and **Shutdown (Switch Off)** work on their machine. These are reported real-hardware outcomes, not independent CI verification. Detailed metric-by-metric validation, agent restart/recovery, and **Windows Wake-on-LAN remain unconfirmed**.

**CPU-temperature routines (owner validation, 2026-11-17):** After packaging/installing the PR #9 Edge Driver update, the owner confirmed that the SmartThings mobile routine editor can create and save conditions with multiple thresholds **above 60 °C** on the existing Gentoo Linux device. Routine-trigger execution at a real hot-CPU threshold was not tested. See [validation notes](docs/development/CPU-TEMPERATURE-RANGE-EXPERIMENT.md).

**Windows CI:** Windows Server 2025 x64 .NET 10 build, contract/HMAC tests, HTTP smoke, `LocalService` installation, protected state and opt-in/opt-out passed. Windows ARM64 was cross-published only; no ARM64 hardware execution.

**SmartThings distribution:** [ARoedl SmartThings Edge Drivers](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), channel `7a23289c-d1f8-42cc-ba10-4ffd219b89bb`, driver `2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7`. The Windows volunteer's report is from the [public beta Community thread](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605).

**Outstanding before stable release:** More than one independent Windows host, Windows WOL from a documented sleep/power state, metrics and recovery validation, upgrade/rollback without identity/key rotation, and network/firmware variations. Do not mistake CI Windows Server tests for a Windows 11 hub interoperability test.

**Release discipline (2026-11-17):** Preserve the v0.5.1-beta.1 assets and protocol v2 as a known-good baseline. Explore changes only on separate branches, test before publishing, and do not merge experimental Windows session locking or temperature-range behavior into the public beta without hardware/app validation.
