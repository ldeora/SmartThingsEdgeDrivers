# Next beta candidate v0.5.2-beta.1 — publisher checklist

PR #13 merged and new disk capacity confirmed on Linux after hub reboot. New verified GitHub prerelease ZIPs, checksums and updated Computer Host LAN channel driver still need to be published. Preserve v0.5.1-beta.1 and its assets as rollback. Windows 11 disk capacity and identity/power preservation need volunteer confirmation. See `docs/beta/RELEASE-NOTES-v0.5.2-beta.1.md` and `docs/beta/UPDATE-v0.5.2-beta.1-COMMENT.md`.

---

# Computer Host LAN — v0.5.1-beta.1 release brief

**Scope:** First community public beta of the independent protocol-v2 Computer Host LAN integration for Linux and Windows. The existing Linux Host LAN project is preserved.

**Hardware evidence:** Gentoo `hydra` with an actual SmartThings hub passed discovery, monitoring, recovery and opt-in reboot/suspend/WOL/shutdown/WOL. Windows Server 2025 GitHub CI passed compile, HMAC/HTTP, `LocalService` installation, protected state, PowerShell 5.1 opt-in/out and self-contained Windows x64 packaging. **Windows 11 hardware discovery and power actions are still unverified.**

**Distribution:** Verified [ARoedl SmartThings Edge Drivers channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20); Computer Host LAN driver is assigned and a separate SmartThings account successfully installed it. [GitHub v0.5.1-beta.1 prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) has been prepared as a **draft** with checksummed Windows x64, Linux source and documentation assets.

**Before forum recruitment:** merge publication-documentation PR, rebuild assets from final `main` SHA and replace existing draft assets, review license/provenance and safety, publish prerelease, then verify public downloads and make the Community announcement.

**Beta disclosure:** Windows package is unsigned; power disabled by default, requires a shared control key and explicit opt-in; local HTTP is unencrypted and for trusted LANs only; no guaranteed WOL from all firmware or Windows S0/S3/S4/S5 modes. Windows ARM64 cross-build and Linux containers are not real-hardware certification.

[Installation](INSTALLATION.md) · [Public beta quick start](docs/beta/START-HERE.md) · [Test checklist](docs/beta/TESTER-CHECKLIST.md) · [Prepared Community post](docs/beta/COMMUNITY-ANNOUNCEMENT.md).
