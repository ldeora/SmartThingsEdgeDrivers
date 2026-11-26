# Computer Host LAN — SmartThings for Linux and Windows

**Upgrading? Run the new installer over your existing installation. Your device, settings, routines and key are kept; nothing needs to be changed in SmartThings.**

**Version 1.0.0-rc.3.** See the [versioned release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3) and [release list](https://github.com/ldeora/SmartThingsEdgeDrivers/releases) for actual download availability. Use the instructions matching the version you downloaded.

Monitor and control your computer in SmartThings, using your trusted local
network. See CPU, RAM, disk usage, uptime and host status; optionally wake,
shut down, reboot or suspend your computer, including through routines.
The Edge driver communicates locally with your computer; no separate cloud
service is required. SmartThings itself still uses its platform services.

## Get started

- [Linux installer Quick Start — rc.3](docs/release/LINUX-INSTALLER-QUICK-START.md)
- [Windows Setup Quick Start — rc.3](docs/release/WINDOWS-QUICK-START.md)
- [SmartThings driver invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) — enroll your hub and install Computer Host LAN.

For the older rc.2 packages see the [rc.2 Quick Start](docs/release/QUICK-START.md).
New computer? Scan nearby once. Existing computer? Refresh its device; do
not delete or re-pair it. Monitoring is enabled by default. Remote power is
optional and requires opt-in on both sides. Use a trusted private LAN; never
forward the agent's HTTP port to the Internet. WOL depends on hardware and
firmware. Verify downloads against the same trusted versioned release.
Packages are unsigned; checksums verify bytes, not publisher identity.

## Maintenance and support

[Upgrade, reinstall, recovery and fresh start](docs/release/UPGRADE.md) ·
[Troubleshooting](docs/release/TROUBLESHOOTING.md) ·
[Detailed installation](INSTALLATION.md) · [Security](SECURITY.md) ·
[Protocol v2](PROTOCOL.md) · [rc.3 release notes](docs/release/RELEASE-NOTES-v1.0.0-rc.3.md)

The rc.3 Linux installer supports setup, power/WOL configuration, repair,
historical restore, interrupted-operation recovery and normal uninstall.
The source ZIP is **source only**, not a Linux installation package.

## Release information

Integration **1.0.0-rc.3**, Linux agent and Edge **0.4.7-rc.3**, Windows agent
**0.2.8-rc.3**, protocol v2. See [release history, security cautions and earlier test evidence](docs/history/RC2-AND-EARLIER.md).
Computer Host LAN is separate from the protocol-v1 Linux Host LAN integration;
do not mix the agents or drivers.
