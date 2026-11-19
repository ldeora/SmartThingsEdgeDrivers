# Computer Host LAN — v0.5.4-beta.1 publication gates

This is a public beta, not a stable Windows certification. Real Windows 11 hub discovery and WOL are beta testing goals, not reasons to withhold the graphical installer once the current source and packaging CI are green.

## Completed

- [x] PR #17 merged; Inno Setup 7 graphical wizard and underlying Windows scripts are in `main`.
- [x] Native Windows Server 2025 GUI/clipboard, hub address field, key handling, monitoring-only and power-enabled wizard navigation passed CI.
- [x] PowerShell ZIP-to-Setup migration, upgrades, preserved identity/key/configuration/power preference and guarded uninstalls passed CI.
- [x] Windows ZIP/PowerShell installation remains available as a fallback.
- [x] Existing SmartThings driver/channel and tested Linux behavior remain unchanged.

## Before publication of v0.5.4-beta.1

- [ ] Merge the v0.5.4-beta.1 packaging/docs PR after Windows Inno, Windows agent, Linux and unified release-candidate checks succeed.
- [ ] Fetch the exact final `main` commit's release-candidate asset set; verify 3 ZIPs, one Setup.exe and `SHA256SUMS.txt`.
- [ ] Verify standalone Setup.exe version against `release.json`, ZIP BUILD-INFO.json and full checksums.
- [ ] Approve redistribution of Inno Setup / Zeroconf / .NET and confirm unsigned SmartScreen and trusted-LAN warnings.
- [ ] Publish a new GitHub **prerelease** `computer-host-lan-v0.5.4-beta.1`, preserving the old v0.5.3-beta.1 files.
- [ ] Verify all public release links/hashes and post the short Windows installer beta update in the existing Community thread.

## After publication: testing

Solicit Windows 11 hardware results for physical hubs (none/one/multiple), mDNS restricted LANs, manual IPv4, LocalSubnet, scaling, migration, service recovery, metrics, suspend/reboot/shutdown and WOL. Explicitly distinguish Windows Server CI from real Windows 11 compatibility tests.

