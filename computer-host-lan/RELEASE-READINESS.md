# Computer Host LAN — v0.5.4-beta.1 release readiness

| Item | Status |
| --- | --- |
| PR #17 guided Windows x64 Setup.exe and Inno wizard merged | PASS — `06cf471ffb18` |
| Windows Server 2025 GUI, clipboard, script-to-Setup migration, upgrade and guarded uninstall | PASS — run 44515639490 |
| Windows 11 physical Setup.exe and real SmartThings hub discovery | Open — beta testing objective |
| Windows PowerShell ZIP retained as a fallback | Implemented; new release candidate must confirm packaging |
| Linux/Edge driver unchanged and protocol v2 compatible | Planned; verify final release candidate |
| Four release assets including Setup.exe and unified SHA256SUMS | Candidate workflow prepared; verify successful CI |
| GitHub v0.5.4-beta.1 prerelease | Not published; owner publication step required |
| SmartThings existing driver/channel | Existing published channel retained; no redeployment necessary |
| Redistribution/provenance (Inno Setup, Zeroconf, .NET) | Publisher sign-off required |
| Unsigned Windows binary, trusted LAN, opt-in power warnings | Disclosed |

Only publish a new versioned prerelease once all release-candidate tests pass on the exact `main` commit; preserve v0.5.3-beta.1 for rollback. No stable-release claims for Windows 11 multi-hub, GUI display scaling, S0/S3/S4/S5 WOL or heterogeneous networks.

