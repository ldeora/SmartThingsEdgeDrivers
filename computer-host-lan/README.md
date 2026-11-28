# Computer Host LAN — SmartThings for Linux and Windows

Monitor and optionally control your computer through SmartThings using a
local Edge driver and lightweight host agent. No additional broker, cloud
account or Home Assistant installation is required; SmartThings itself
uses its platform services.

**Current published release: [v1.0.0-rc.3](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3).**
Use version-matched packages from the release, not CI artifacts or development
source scripts. This working branch may contain documentation improvements
since that tag; it is not a new binary release.

## Get started

| Guide | What it covers |
| --- | --- |
| [Install on Windows](docs/install-windows.md) | Graphical Setup, PowerShell fallback, installed components and uninstall |
| [Install on Linux](docs/install-linux.md) | Standalone terminal installer, configuration and maintenance |
| [SmartThings setup](docs/smartthings.md) | [Driver invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), device tile, metrics, power, preferences and routines |
| [Upgrade and maintenance](docs/upgrade.md) | Upgrade, repair, restore, recovery, reinstall and fresh start |
| [Troubleshooting](docs/troubleshooting.md) | Network, power, metrics, diagnostics and support |
| [Volunteer testing](docs/testing.md) | Practical acceptance checklist |
| [Security and privacy](SECURITY.md) | Trust model, credentials, limitations, security reporting |
| [Release notes](docs/release/RELEASE-NOTES-v1.0.0-rc.3.md) | Current changes and limitations |

**Upgrading?** Run the new installer over the existing installation. Keep
identity, key, settings, routines and the same SmartThings device; refresh
rather than re-pair. Do not uninstall first. Power control is opt-in.

## Platforms and requirements

A trusted private LAN and SmartThings hub running Edge are required.
Agent HTTP defaults to TCP 8765; discovery uses UDP 5353/mDNS. Do not forward
the port to the Internet. See [security](SECURITY.md).

| Platform | Requirements and qualification |
| --- | --- |
| Linux | x86-64, systemd, Python 3.10+, Avahi for discovery. Exact published rc.3 installer upgraded rc.2 on Gentoo with a real hub; monitoring, identity, tile and shutdown/wake passed. Debian, Ubuntu and Fedora have automated container/source coverage, not physical hardware certification. |
| Windows | Windows 11 x64 target; self-contained .NET runtime. Automated Windows Server CI includes installer, service and protocol checks. Earlier volunteer hardware tests are positive; final rc.3 hardware scope remains tracked separately. |
| Windows ARM64 | Cross-build only, no qualified ARM64 graphical installer. |

WOL depends on Ethernet adapter, firmware, network and OS power state;
Linux automated persistent WOL supports wired Ethernet only. Neither CI nor
publication establishes every computer's power-state compatibility.

## Release and source

Integration 1.0.0-rc.3; Linux agent/Edge 0.4.7-rc.3; Windows agent 0.2.8-rc.3;
protocol v2. See [release history](CHANGELOG.md) and the [qualification record](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/119).
The packages are unsigned: verify SHA-256 against the trusted versioned
release; checksums do not authenticate the publisher. The source ZIP is
source only, not a Linux installer. Do not mix protocol-v1 Linux Host LAN
agents/drivers with Computer Host LAN.

[Protocol reference at the rc.3 tag](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/PROTOCOL.md) ·
[Source and component documentation](https://github.com/ldeora/SmartThingsEdgeDrivers/tree/main/computer-host-lan) ·
[Third-party notices](docs/THIRD-PARTY-NOTICES.md) · [Apache-2.0 licence](LICENSE).
