# Computer Host LAN beta distribution — release engineering

This directory is used by the owner to **prepare** a release from a fixed reviewed commit.

## Candidate CI, not publication

The [beta candidate workflow](../../../.github/workflows/computer-host-release.yml)
runs Windows x64 publish/HTTP tests, creates a self-contained Windows ZIP,
and creates Linux source and documentation archives. SHA-256 manifests are
generated from the exact bytes published. CI unpacks and validates all assets
before archiving a candidate. GitHub Actions artifacts expire; **do not use their
URLs in a public SmartThings Community announcement**.

## Publishing (after PR merge and channel verification)

1. Make sure both platform CI jobs and the release-candidate workflow are green
   on the intended commit on main. Review changes and author/licensing notices.
2. Download the single release-candidate artifact for that commit and inspect
   source ZIP, Windows ZIP, documentation, and checksums.
3. Use a namespaced annotated tag such as
   computer-host-lan-v0.5.1-beta.1 **only when release versions match contents**.
   The current development integration version is 0.5.1-dev.1, so a beta.1 tag
   requires an explicit controlled version change first.
4. Draft a GitHub prerelease; attach individually verified release ZIPs and
   SHA256SUMS.txt; clearly mark Windows binaries as **unsigned**.
5. Verify the release downloads and their checksums as a new user. Do not
   publish an invitation or promise full Windows 11 compatibility yet.
6. Obtain and verify the SmartThings Computer Host LAN beta Edge channel invite,
   driver ID and public tester onboarding from a second account/hub.

### What is not validated

Windows 11 host mDNS discoverability from a real SmartThings hub, physical
Windows reboot, suspend, shutdown, wake from S3/Modern Standby/S4/S5, and
ARM64 runtime behavior are the subject of volunteer hardware testing.
Linux cross-distro CI is container/source validation, not a physical WOL pass.

No automated job in this repository creates tags, publishes releases, signs
binaries, changes your production SmartThings channel, or activates real power.
