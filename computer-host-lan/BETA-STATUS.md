# Computer Host LAN — public beta v0.5.1-beta.1

**Integration:** 0.5.1-beta.1. Linux agent and Edge Driver: 0.4.0-dev.1. Windows agent: 0.2.0-alpha.1. Protocol: v2.

**Linux reference hardware:** Gentoo Linux `hydra` and a real SmartThings hub passed discovery, telemetry, service loss/recovery, reboot, suspend/WOL and shutdown/WOL.

**Windows CI:** .NET 10 Windows Server 2025 x64 build, contract and HMAC tests, HTTP smoke, service installation as `LocalService`, protected state, opt-in/opt-out under PowerShell 5.1. No physical Windows power commands were executed in CI. Windows ARM64 cross-published only.

**SmartThings distribution:** [ARoedl SmartThings Edge Drivers](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), channel `7a23289c-d1f8-42cc-ba10-4ffd219b89bb`, driver `2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7`. Another SmartThings account successfully installed the driver from this channel; that does not prove Windows 11 discovery or app presentation.

**GitHub assets:** Built with checksums on `main` commit `eb277dde` ([successful workflow](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43839028249)). The owner created a **draft** [v0.5.1-beta.1 prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) with four assets. After final documentation is merged, replace draft assets with a newly validated build from the updated `main` commit before publishing. Do not distribute temporary Actions artifacts.

**Still to verify before the forum post:** published release asset downloads and hashes, licensing/provenance, and absence of misleading claims. Windows 11 physical discovery, suspend/WOL and shutdown/WOL are volunteer beta objectives, not prepublication gates.
