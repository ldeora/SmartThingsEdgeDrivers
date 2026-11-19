# Computer Host LAN — v0.5.4-beta.1 publication and next-stage gates

**Already published:** GitHub prerelease
[Computer Host LAN v0.5.4-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1),
2026-11-19, from commit `f19c114b1cca7dcb87b5774eff7602e70184047c`.
Four complete workflows passed; the publisher verified the release SHA-256
manifest and published the three ZIPs, unsigned Setup.exe and SHA256SUMS.txt.

**New field evidence (2026-11-19):** Windows 11 Pro tester reports successful
native Setup installation and GUI upgrade, with accurate SmartThings metrics.
This supersedes the statement that the GUI was tested only on Windows Server.

**Stabilization now in progress:** [draft PR #19](https://github.com/ldeora/SmartThingsEdgeDrivers/pull/19).
Its source must not be mistaken for the released beta. The first stable
candidate has separate CI, Windows hardware, licensing and security gates.
See [release readiness](../../RELEASE-READINESS.md) for the actionable list.

The v0.5.3 and v0.5.4 release assets, existing SmartThings channel and
unchanged protocol-v2 device identities are preserved. Publishing an RC
requires fresh package checksums and an explicit owner decision; CI never
silently creates a GitHub release or updates the SmartThings channel.
