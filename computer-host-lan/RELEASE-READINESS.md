# Computer Host LAN — prerelease readiness

| Gate | Status | Evidence / next step |
| --- | --- | --- |
| Separate repository directory / legacy isolation | PASS | `computer-host-lan/`; existing `linux-host-lan/` kept |
| Linux core reference | PASS on Gentoo | Real SmartThings hub tests, 2026-11-16 |
| Windows x64 compile + API smoke | PASS in CI | [Windows run](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333) |
| Windows LocalService install and opt-in/out | PASS in CI | PowerShell 5.1, state ACLs; no physical power command |
| Windows ARM64 hardware | OPEN | Cross-published only |
| Real Windows 11 mDNS / SmartThings pairing | OPEN | Purpose of volunteer beta |
| Reproducible fixed-commit release assets | CANDIDATE CI PASSED | [PR #4 release workflow](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43835476167); final tagged-commit build still required |
| Driver channel invitation / cross-account app | OPEN | Owner must publish/test |
| Support, privacy, license provenance review | OPEN | Final prerelease checklist |

## Release boundary

A beta may ship before hardware validation across Windows 11 variants, but must have a functioning verified installer, recoverable uninstall, permanent checksummed assets, accurate documentation and no unsupported compatibility claims. Local HTTP is intentionally **not** TLS secured; only trusted private LANs and scope-limited firewall rules should be used. Power remains disabled by default.

The files in `docs/history/v0.3.1-beta.1/` document the **older Linux-only** project and are not current Computer Host LAN instructions.
