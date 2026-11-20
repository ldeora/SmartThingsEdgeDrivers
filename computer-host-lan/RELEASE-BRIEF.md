# Computer Host LAN v0.5.5-beta.1 — candidate release brief

> **Next candidate: Computer Host LAN v0.5.6-beta.1 (not yet published).** This single hardening candidate combines installer recovery and runtime resilience. Current published/tested beta: [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1). [Candidate release notes](docs/beta/RELEASE-NOTES-v0.5.6-beta.1.md).


**Not yet released.** Follow-up to the stabilization PR #19 (merged main commit `0978dd75557ce8b3b38693cdf740aaa2585ab0fa`), with Windows agent v0.2.4-beta.1, Linux agent / Edge driver v0.4.3-beta.1, and unchanged protocol v2. The installer is still unsigned; GUI setup remains the recommended Windows method and ZIP/PowerShell remains supported.

**Sequence:** new versioning PR → all four CI workflows on final merged commit → verify source SHA, four deliverable checksums and embedded component versions → publish a *new* prerelease `computer-host-lan-v0.5.5-beta.1` → package/assign the updated Edge driver to the *existing* channel → validate Windows 11 and Gentoo upgrade/recovery → announce. Keep v0.5.4-beta.1 as a rollback option. No workflow automatically creates a release or deploys the Edge driver.

[Release notes](docs/beta/RELEASE-NOTES-v0.5.5-beta.1.md) · [Publication gates](docs/beta/PUBLICATION-GATES.md) · [Stable-release readiness](RELEASE-READINESS.md)

---

> **Historical publication brief.** The v0.5.4-beta.1 release was published on
> 2026-11-19 from `f19c114b1cca7dcb87b5774eff7602e70184047c`.
> The uncompleted instructions below describe its *former publication process*.
> For the ongoing first stable-candidate work see [release readiness](RELEASE-READINESS.md)
> and [draft PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19).
> Do not follow these steps to re-publish an existing tag.

# Computer Host LAN v0.5.4-beta.1 — release and publication checklist

**Goal:** Make the unsigned graphical Windows x64 Setup.exe the preferred public-beta installation and upgrade method, keeping Windows ZIP/PowerShell as a supported fallback. The Linux agent and Edge driver stay at v0.4.2-beta.1; Windows agent becomes v0.2.3-beta.1; protocol v2 unchanged.

1. Confirm PR #17 merge `06cf471ffb18` and merge the release follow-up only after its Windows Inno GUI, Windows runtime, Linux tests and unsigned release-candidate CI pass.
2. Identify the exact final `main` commit. Download the **computer-host-lan-complete-unsigned-beta-candidate** CI artifact for that SHA. Confirm exactly **four deliverables**: `computer-host-lan-v0.5.4-beta.1-windows-x64-unsigned-setup.exe`, `computer-host-lan-v0.5.4-beta.1-windows-x64-unsigned.zip`, `computer-host-lan-v0.5.4-beta.1-source.zip`, `computer-host-lan-v0.5.4-beta.1-documentation.zip`, plus `SHA256SUMS.txt`. Check all hashes, version metadata, source commit and Windows ZIP internal manifest.
3. Review redistribution/provenance of Inno Setup 7, Zeroconf 3.7.16, bundled .NET 10 runtime and other third-party dependencies; confirm the unsigned/SmartScreen and trusted-LAN disclosure.
4. Publish a **new GitHub prerelease** `computer-host-lan-v0.5.4-beta.1` with the four files and `SHA256SUMS.txt`; do not replace v0.5.3-beta.1 files. Test all public download URLs and hashes after publication.
5. The Computer Host LAN Edge driver is **unchanged**; do not unnecessarily repackage/reassign the existing SmartThings driver or change channel ID `7a23289c-d1f8-42cc-ba10-4ffd219b89bb`. The verified invitation remains https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20.
6. Once the release exists, post `docs/beta/UPDATE-v0.5.4-beta.1-COMMENT.md` to the existing [SmartThings Community beta thread](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605) and link the new [installation guide](INSTALLATION.md).

**Do not publish before verifying release CI:** Windows Server 2025 wizard tests are strong evidence, but not physical Windows 11 hub tests. The public beta is intended to collect the remaining data. There is no automatic signing, release publication or channel update in CI.

---


# Computer Host LAN — v0.5.1-beta.1 release brief

**Scope:** First community public beta of the independent protocol-v2 Computer Host LAN integration for Linux and Windows. The existing Linux Host LAN project is preserved.

**Hardware evidence:** Gentoo `hydra` with an actual SmartThings hub passed discovery, monitoring, recovery and opt-in reboot/suspend/WOL/shutdown/WOL. Windows Server 2025 GitHub CI passed compile, HMAC/HTTP, `LocalService` installation, protected state, PowerShell 5.1 opt-in/out and self-contained Windows x64 packaging. **Windows 11 hardware discovery and power actions are still unverified.**

**Distribution:** Verified [ARoedl SmartThings Edge Drivers channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20); Computer Host LAN driver is assigned and a separate SmartThings account successfully installed it. [GitHub v0.5.1-beta.1 prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) has been prepared as a **draft** with checksummed Windows x64, Linux source and documentation assets.

**Before forum recruitment:** merge publication-documentation PR, rebuild assets from final `main` SHA and replace existing draft assets, review license/provenance and safety, publish prerelease, then verify public downloads and make the Community announcement.

**Beta disclosure:** Windows package is unsigned; power disabled by default, requires a shared control key and explicit opt-in; local HTTP is unencrypted and for trusted LANs only; no guaranteed WOL from all firmware or Windows S0/S3/S4/S5 modes. Windows ARM64 cross-build and Linux containers are not real-hardware certification.

[Installation](INSTALLATION.md) · [Public beta quick start](docs/beta/START-HERE.md) · [Test checklist](docs/beta/TESTER-CHECKLIST.md) · [Prepared Community post](docs/beta/COMMUNITY-ANNOUNCEMENT.md).
