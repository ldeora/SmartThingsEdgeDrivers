# Next candidate: Computer Host LAN v0.5.4-beta.1 — Windows guided installer

The existing public release is **v0.5.3-beta.1**. PR #17 (merge commit `06cf471ffb18`) adds the Inno Setup 7 Windows x64 wizard to `main`. Windows Server 2025 CI has passed native wizard interactions, opt-in and key copy, ZIP-to-Setup migration, upgrades, guarded service removal, uninstall and preserved identity/configuration. This is sufficient to include Setup.exe as an **unsigned beta download**; it is not evidence of physical Windows 11 hub interoperability.

The planned **v0.5.4-beta.1** release makes Setup.exe the default Windows installation and upgrade method and keeps the existing Windows ZIP/PowerShell script method available. Fresh installs start in monitoring-only mode, while guided upgrades preserve previous optional power enablement. Manual script upgrades still require `-EnablePower`. Linux and the Edge Driver remain at v0.4.2-beta.1; the Windows agent moves to v0.2.3-beta.1; protocol v2 and the existing shared SmartThings channel stay unchanged.

**Required before publication:** merge the release packaging/documentation follow-up PR with successful CI; verify the exact `main` commit's release-candidate bundle includes Linux ZIP, Windows ZIP, docs ZIP, Windows Setup.exe and `SHA256SUMS.txt`; confirm component versions and SHA-256 checksums; review third-party redistribution licenses and signing/safety wording; publish a **new prerelease** `computer-host-lan-v0.5.4-beta.1`; verify permanent public downloads. Preserve v0.5.3-beta.1 unchanged.

**Open beta test requests:** real Windows 11 hub mDNS discovery (zero, one and multiple hubs), manual IPv4, local-network fallback, GUI at different scaling, migration of real previous-beta hosts, app pairing, monitoring, recovery and WOL. These are not stable-release blockers, but results must be explicitly described.

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
