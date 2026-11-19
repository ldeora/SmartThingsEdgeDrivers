> **Historical v0.5.1-beta.1 plan.** This document is archived for
> provenance; its unchecked boxes are not current publication tasks.
> The current published release is
> [v0.5.4-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1).
> For future release gates see [RELEASE-READINESS.md](RELEASE-READINESS.md).

# Computer Host LAN — v0.5.1-beta.1 distribution plan

## Completed
- [x] Implement separate protocol-v2 project without modifying the existing `linux-host-lan/`.
- [x] Validate Linux discovery/metrics/recovery and opt-in power/WOL on real Gentoo `hydra`.
- [x] Windows x64 .NET 10 compilation, HTTP/HMAC tests, service installation and opt-in/out on Windows CI; ARM64 cross-publish labeled experimental.
- [x] Merge the integration, packaging and beta version PRs (#3–#5).
- [x] Produce a fixed-commit Linux source ZIP, docs ZIP and unsigned Windows x64 tester kit with SHA-256 verification.
- [x] Create draft prerelease `computer-host-lan-v0.5.1-beta.1` with four assets.
- [x] Verify [existing shared channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), assigned Computer Host LAN driver and installation from another SmartThings account.
- [x] Prepare public release notes, copyable installation commands, structured tester checklist and Community announcement.

## Before publishing
- [ ] Merge final channel/onboarding documentation update and pass CI.
- [ ] Refresh draft release assets and notes from the new *exact* `main` commit, checking Windows BUILD-INFO.json, source release.json and SHA-256 checksums.
- [ ] Publisher approves license/provenance and security wording.
- [ ] Publish GitHub prerelease as a **prerelease**; verify four permanent public assets and hashes.
- [ ] Post the [prepared Community invitation](docs/beta/COMMUNITY-ANNOUNCEMENT.md), with GitHub Release and verified channel links.

## Beta hardware tasks (not blockers)
Real Windows 11 LAN/mDNS pairing, correct profile/metrics, Windows power/S0/S3/S4/S5 and WOL, and more Linux distributions. No claims of MSI/DEB/RPM, signing or auto-update.
