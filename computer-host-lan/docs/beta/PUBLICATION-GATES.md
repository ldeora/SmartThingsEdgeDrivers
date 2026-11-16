# Computer Host LAN — public beta publication gates

This beta is specifically intended to recruit Windows 11 and additional Linux hardware testers. Physical Windows WOL, suspend and full shutdown are **not** prerequisites for the first public testing announcement.

## Completed
- [x] Separate protocol-v2 Computer Host LAN Edge Driver and agents; original Linux Host LAN unchanged.
- [x] Linux real-hardware reference and Windows x64 compile, HTTP/HMAC, Windows Service install and power opt-in/out tests.
- [x] Linux distro CI and Windows ARM64 cross-publish clearly distinguished from hardware validation.
- [x] Source license file present (Apache-2.0); final third-party provenance still requires owner approval.
- [x] Project/packaging/beta-version PRs merged into `main` (#3, #4, #5).
- [x] Versioned ZIP archives and checksums built and verified from CI; Windows package verified after extraction under Windows PowerShell 5.1.
- [x] Verified existing [ARoedl SmartThings Edge Drivers channel](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), assigned Computer Host LAN driver, and successful installation from a separate account.
- [x] GitHub issue template, privacy guidance, hardware checklist, release notes and Community announcement prepared.
- [x] Disclose unsigned Windows executable, unencrypted trusted-LAN-only HTTP, default-disabled power and uncertain Windows sleep/WOL.

## Still required to publish
- [ ] Merge final documentation PR and check all three workflows on its merge commit.
- [ ] Refresh the existing GitHub draft-release ZIPs and notes from that exact merge commit; verify hashes and source commit.
- [ ] Publisher confirms copyright, third-party attribution and terms for redistributed binaries.
- [ ] Publish the [v0.5.1-beta.1 prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) and verify public asset downloads/checksums.
- [ ] Post the Community announcement with the permanent release URL and verified SmartThings invitation.

## After publication: volunteer tests
Windows 11 hub discovery/native DNS-SD, profile and telemetry, S0/S3/S4/S5, Fast Startup, suspend/reboot/shutdown and Wake-on-LAN; wider Linux distributions and hardware. Native MSI, DEB/RPM, code signing, auto-updates and ARM64 hardware support can follow later.

Source evidence: [release CI on `main`](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43839028249), original merge commit `eb277dde`. Revalidate from the final documentation merge commit.
