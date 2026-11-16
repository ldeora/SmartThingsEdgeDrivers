# Computer Host LAN — operating system test matrix

See [the live evidence matrix](docs/beta/COMPATIBILITY-STATUS.md). This page is the entry point for the cross-platform beta; historical Linux v0.3.1 source tests are archived in `docs/history/v0.3.1-beta.1/`.

| Platform | Evidence |
| --- | --- |
| Gentoo Linux (systemd, Python 3.14) | Physical `hydra` SmartThings end-to-end pass |
| Debian 12/13, Ubuntu 24.04/26.04, Fedora 43/44 | CI container source and installer smoke, **not** real PID1 service/power |
| Windows Server 2025 x64 | .NET 10 build, local HTTP, native service install and opt-in/out CI |
| Windows 11 x64 | Requires volunteer hardware testing, especially mDNS and WOL |
| Windows ARM64 | Build/publish only, no hardware execution |
| Other Linux distros | Unsupported until suitable testing |

Windows WOL depends on NIC, firmware, power policy, and actual sleep/shutdown state. Linux WOL depends on NIC, network manager, firmware and persistence across reboot. Neither platform supports an unqualified “wake every PC” claim.
