# Next beta v0.5.3-beta.1 — publisher checklist

PR #15 is merged; on 2026-11-18 the publisher tested four values for RAM and filesystem on actual Gentoo Linux `hydra` + SmartThings hub, including English/German capability schema and app presentation. New optional v2 fields introduce no identity, power or profile changes. Linux/Edge 0.4.2-beta.1; Windows 0.2.2-beta.1. Windows 11 real-hardware testing of new measurements is the remaining beta objective.

1. Confirm final `main` SHA and green Linux, Windows and release-candidate GitHub Actions runs for that exact SHA.
2. Download the final `computer-host-lan-complete-unsigned-beta-candidate` artifact; verify the three ZIPs against SHA256SUMS, source release manifest and Windows BUILD-INFO commit/version.
3. Publish [v0.5.3-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1) as a **new GitHub prerelease** with the three ZIPs and `SHA256SUMS.txt`; preserve v0.5.2-beta.1 tag/assets for rollback.
4. Package and assign the updated Computer Host LAN Edge driver to the **existing** channel, keeping driver ID `2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7`. Do not install unrelated drivers.
5. Only after both distributions are ready, post `docs/beta/UPDATE-v0.5.3-beta.1-COMMENT.md` to the existing SmartThings Community beta thread.

No release or channel deployment is performed by CI. 

---

# Computer Host LAN — v0.5.1-beta.1 release brief

**Scope:** First community public beta of the independent protocol-v2 Computer Host LAN integration for Linux and Windows. The existing Linux Host LAN project is preserved.

**Hardware evidence:** Gentoo `hydra` with an actual SmartThings hub passed discovery, monitoring, recovery and opt-in reboot/suspend/WOL/shutdown/WOL. Windows Server 2025 GitHub CI passed compile, HMAC/HTTP, `LocalService` installation, protected state, PowerShell 5.1 opt-in/out and self-contained Windows x64 packaging. **Windows 11 hardware discovery and power actions are still unverified.**

**Distribution:** Verified [ARoedl SmartThings Edge Drivers channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20); Computer Host LAN driver is assigned and a separate SmartThings account successfully installed it. [GitHub v0.5.1-beta.1 prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) has been prepared as a **draft** with checksummed Windows x64, Linux source and documentation assets.

**Before forum recruitment:** merge publication-documentation PR, rebuild assets from final `main` SHA and replace existing draft assets, review license/provenance and safety, publish prerelease, then verify public downloads and make the Community announcement.

**Beta disclosure:** Windows package is unsigned; power disabled by default, requires a shared control key and explicit opt-in; local HTTP is unencrypted and for trusted LANs only; no guaranteed WOL from all firmware or Windows S0/S3/S4/S5 modes. Windows ARM64 cross-build and Linux containers are not real-hardware certification.

[Installation](INSTALLATION.md) · [Public beta quick start](docs/beta/START-HERE.md) · [Test checklist](docs/beta/TESTER-CHECKLIST.md) · [Prepared Community post](docs/beta/COMMUNITY-ANNOUNCEMENT.md).
