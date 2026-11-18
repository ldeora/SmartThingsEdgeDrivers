# Computer Host LAN — change log

## v0.5.3-beta.1 (2026-11-18) — four-value resource telemetry (candidate)

- PR #15 adds exact RAM used/available and root/system filesystem allocated/available byte metrics on Linux and Windows; existing percent/total readings remain unchanged.
- SmartThings `computerMemoryUsage` and `computerDiskUsage` now display Usage %, Total GiB, Used GiB, Available GiB with English/German translations and responsive app layout.
- Linux Gentoo hydra + real hub validation passed 2026-11-18; all eight readings populated, existing events/automations retained. A transient memory-translation HTTP 422 succeeded after retry.
- Windows agent measurements tested in CI; Windows 11 hardware validation of new values remains a beta objective. No protocol, discovery, identity or power-control changes.
- Linux and Edge Driver v0.4.2-beta.1, Windows agent v0.2.2-beta.1; preserved v0.5.2-beta.1 as published baseline.


## v0.5.2-beta.1 (2026-11-18) — filesystem-capacity beta update (published)

- PR #13 adds `disk_root_total_bytes` for Linux root and Windows system volume, mapped to a new SmartThings `diskTotalGiB` readout alongside disk usage %.
- Additional field is optional and protocol v2 is unchanged. Existing UUIDs, keys, discovery, power behavior and device profiles remain compatible.
- Verified on real SmartThings hub with Gentoo Linux after a hub reboot refreshed the updated custom capability; Windows implementation passed CI, but Windows 11 hardware capacity remains an important beta test.
- Versioned next-beta candidate: Linux agent and Edge Driver v0.4.1-beta.1, Windows agent v0.2.1-beta.1.
- Published GitHub prerelease and assigned matching driver to the existing channel on 2026-11-18; v0.5.1-beta.1 assets are preserved.


## v0.5.1-beta.1 (2026-11-16) — public-beta release candidate

- Cross-platform Computer Host LAN integration packaged for volunteer testing with an independently versioned protocol-v2 Linux agent, shared Edge Driver and native Windows Host Agent.
- GitHub CI now assembles and verifies a complete unsigned Windows x64 kit (installer, verifier, sanitized diagnostics, test checklist and license) alongside Linux source and documentation archives, using SHA-256 manifests.
- No changes to the hardware-validated Linux agent and Edge Driver runtime; Windows 11 mDNS discovery and physical power/WOL compatibility remain **untested**.
- Publication is **pending** final versioned CI, copyright/provenance review, permanent GitHub Release assets and a working SmartThings beta channel invitation.

## v0.5.1-dev.1 (2026-11-16) — cross-platform CI candidate

- Retains the Linux v0.4.0-dev.1 reference agent and its hardware-validated SmartThings Edge Driver behavior.
- Native Windows Host Agent v0.2.0-alpha.1 provides CPU/RAM/drive/uptime telemetry, Windows Service and DNS-SD registration, opt-in HMAC-authenticated reboot/shutdown/suspend and candidate WOL metadata.
- Windows Server 2025 x64 CI verified compilation, self-contained publishing, protocol/HMAC tests, HTTP smoke, LocalService installation, protected state, and PowerShell 5.1 opt-in/out. Real Windows 11 SmartThings and hardware power behavior remain **unverified**.
- Windows ARM64 cross-publish verified; runtime untested.
- Separate `computer-host-lan/` project directory; independent `linux-host-lan/` retained.
- Follow-up repository cleanup updates active CI workflows, versioned source-manifest generation, current beta guidance and issue reporting. No Windows or Linux runtime changes in that cleanup.
- Not yet a released public-beta version. No SmartThings channel invitation or permanent GitHub release assets yet.

## v0.5.0-dev.1 (2026-11-16) — Windows monitoring source

Initial Windows monitoring agent implementation and test scaffolding.

## v0.4.0-dev.1 (2026-11-16) — generic protocol v2

New `_computerhost._tcp` discovery, `computer-host-agent` API v2, shared driver, platform-specific profiles and custom monitoring capabilities. Linux successfully validated on Gentoo `hydra`.

Older Linux-only release history: [archived change log](docs/history/v0.3.1-beta.1/CHANGELOG.md).
