# Next candidate: Computer Host LAN v0.5.2-beta.1 — not yet published

PR #13 merged 2026-11-18. Linux real-hub test confirmed `diskTotalGiB = 431.8` after restarting the hub, which refreshed the custom capability. Source versions prepared: Linux agent and Edge Driver v0.4.1-beta.1, Windows agent v0.2.1-beta.1. Windows new disk total has CI coverage but still requires Windows 11 hardware beta feedback. Publish only after final main-commit CI and release assets verification; the prior v0.5.1-beta.1 is intact.

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
