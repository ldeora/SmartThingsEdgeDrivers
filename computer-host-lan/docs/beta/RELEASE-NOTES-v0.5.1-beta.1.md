# Computer Host LAN v0.5.1-beta.1 — public beta

**Computer Host LAN** is a local SmartThings Edge integration for monitoring Linux and Windows computers and, when explicitly enabled, controlling selected power operations. It consists of a cross-platform **Computer Host LAN Edge Driver** and a small agent running on each computer. It is separate from the original Linux-only **Linux Host LAN** driver.

## Downloads and driver channel

The official release page is [Computer Host LAN v0.5.1-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1). Download the assets from that page and verify them with the attached `SHA256SUMS.txt` before installation.

- **Windows 11 x64:** `computer-host-lan-v0.5.1-beta.1-windows-x64-unsigned.zip` — self-contained Windows service, installer/uninstaller, checksum verifier, sanitized diagnostics and checklist.
- **Linux (systemd):** `computer-host-lan-v0.5.1-beta.1-source.zip` — Python host agent and installer, shared Edge Driver sources and tests.
- **Documentation:** `computer-host-lan-v0.5.1-beta.1-documentation.zip` — installation, technical and volunteer testing guides.
- **Checksums:** `SHA256SUMS.txt`.

**SmartThings Edge Driver invitation:** [ARoedl SmartThings Edge Drivers](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). Sign in with your Samsung account, accept, enroll your hub, choose **Available Drivers**, and install **Computer Host LAN**. The existing shared channel contains other drivers too; only Computer Host LAN is needed. External channel installation has been confirmed.

**Start here:** [beta quick start](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/main/computer-host-lan/docs/beta/START-HERE.md) · [installation guide](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/main/computer-host-lan/INSTALLATION.md) · [hardware test checklist](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/main/computer-host-lan/docs/beta/TESTER-CHECKLIST.md) · [GitHub issue reporting](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose).

## Capabilities

Both agents expose CPU utilization, memory and disk usage, uptime and online availability over a local TCP 8765 HTTP API, with automatic `_computerhost._tcp` mDNS discovery. Linux additionally reports CPU temperature and load where available; Windows **does not fabricate those readings**.

A switch and dedicated actions allow Wake-on-LAN and optional authenticated reboot, suspend and shutdown. Power management is **disabled by default** and requires opt-in on the host and in SmartThings. It uses a shared secret and challenge-based HMAC authentication; never share that secret.

## What has been tested

- **Linux:** Real SmartThings hub with Gentoo Linux (`hydra`): discovery, telemetry, service recovery, reboot, suspend followed by WOL, and shutdown followed by WOL.
- **Windows:** Windows Server 2025 x64 GitHub Actions: .NET 10 build, protocol/HMAC tests, telemetry, local HTTP smoke, actual `LocalService` installation, protected persistent state, and PowerShell 5.1 power opt-in/out. The Windows binary is self-contained and **unsigned**.
- **Additional CI:** Linux Python 3.10–3.14 and Debian, Ubuntu, Fedora source/container tests. Windows ARM64 cross-publish was successful, but ARM64 hardware has **not** been tested.

## What we need volunteer testers for

The first priority is **Windows 11 x64 on real hardware**: installation as a Windows Service, LAN discovery from a real SmartThings hub, the Windows profile and metric updates, recovery after service interruption and reboot. We also welcome Linux testers on Debian, Ubuntu, Fedora and other systemd distributions.

Optional hardware power tests should proceed in this order: **reboot → suspend/WOL → shutdown/WOL**. Save open work and have physical access to the test computer first. Windows Modern Standby, S3/S4/S5, Fast Startup, firmware and NIC settings determine whether waking actually works; compatibility is **not guaranteed**. A `202 Accepted` power response only means the action was scheduled.

## Security, privacy and feedback

Use **only on a trusted private LAN**. Local HTTP telemetry is not TLS-encrypted; restrict TCP 8765 to the SmartThings hub wherever possible and never forward the port to the Internet. Begin with monitoring-only installation on a test machine.

Please report results using the [structured checklist](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/main/computer-host-lan/docs/beta/TESTER-CHECKLIST.md) and the [Computer Host LAN issue template](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose). The kit contains a sanitized Windows diagnostic collector. **Review reports manually:** never publish the control token, IP/MAC addresses, host UUID, SmartThings account/location IDs, authentication headers or raw logs.

**Versions:** integration `0.5.1-beta.1`; Linux agent `0.4.0-dev.1`; Edge Driver source `0.4.0-dev.1`; Windows agent `0.2.0-alpha.1`; protocol v2.

This is an experimental community beta, not a signed or certified product. There are no automatic updates, MSI/DEB/RPM installers, or guarantees for unattended/critical computers.
