# Computer Host LAN v0.5.1-beta.1 — public beta release notes (draft)

> **Draft only:** These notes are prepared for the first Computer Host LAN GitHub prerelease. They are not evidence that the prerelease or a SmartThings channel invitation is live.

This is the first cross-platform **Computer Host LAN** beta for SmartThings Edge. It is independent of the original **Linux Host LAN** project. Both host agents use the same protocol v2 (`/v2` HTTP API and `_computerhost._tcp` mDNS service) and the same Computer Host LAN Edge Driver.

## What's included

- **Linux:** Python/systemd/Avahi host agent, CPU temperature where supported, CPU and RAM/disk usage, uptime, Linux load, automatic discovery, opt-in authenticated shutdown/reboot/suspend and SmartThings-hub Wake-on-LAN.
- **Windows x64:** self-contained .NET 10 executable, Windows Service under LocalService, native DNS-SD registration, Win32 CPU/RAM/disk/uptime metrics, opt-in HMAC-authenticated best-effort reboot/shutdown/suspend, candidate WOL MAC/broadcast data for hub-triggered wake.
- Power commands **disabled by default**. Separate optional installation opt-in and SmartThings device preference required.
- Installation scripts, Windows diagnostic collector, integrity checker, structured tester checklist, release checksums, and uninstall instructions.

## Verified

- Real Gentoo Linux `hydra` plus SmartThings hub: discovery/telemetry, agent interruption and recovery, reboot, suspend/WOL, and full shutdown/WOL power cycle.
- Windows Server 2025 x64 GitHub Actions: .NET compile/run, protocol and security contract tests, HTTP smoke, LocalService installation, protected state, PowerShell 5.1 power opt-in/opt-out. No actual Windows shutdown/reboot/suspend command was sent.
- Windows ARM64 cross-compilation only; **not** an ARM64 hardware claim.
- Linux Python 3.10–3.14 and Debian/Ubuntu/Fedora source/container tests, not full hardware or real systemd PID1 certification.

## Not yet verified

Windows 11 discovery from a real SmartThings hub, Windows native mDNS behavior on typical LANs, actual Windows power transitions, S0/S3/S4/S5 and Fast Startup WOL support; non-Gentoo Linux hardware configurations and cross-account channel onboarding. These are the reasons for public volunteer testing.

## Download / install

After publication, obtain the three release ZIPs and `SHA256SUMS.txt` from the **official, permanent GitHub Release** for tag `computer-host-lan-v0.5.1-beta.1`. Verify SHA-256 before extraction.

The Windows kit is unsigned. Run the bundled package verifier, start with monitoring-only installation on a test computer, and only consider power operations with physical recovery available. Do not bypass security controls indiscriminately or use the initial beta on unattended/critical systems.

Install the **Computer Host LAN** Edge Driver via the publisher's separately supplied, verified SmartThings beta-channel invitation. The old Linux Host LAN driver is protocol v1 and is not interchangeable.

Guides: [quick start](START-HERE.md) · [installation](../../INSTALLATION.md) · [test checklist](TESTER-CHECKLIST.md) · [feedback/privacy](FEEDBACK-AND-SUPPORT.md).

## Support and safety

Submit reproducible reports using the [Computer Host LAN issue template](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose) and the test case ID. Never post the host's HMAC control token, IP/MAC, UUID, SmartThings account/location identifiers, or unredacted logs. Use the bundled sanitized diagnostics and review output before publishing it.

Local HTTP telemetry is not encrypted, so limit TCP 8765 to the SmartThings hub on a trusted private LAN. Power request acceptance (HTTP 202) means the action was scheduled; it does not guarantee physical completion. WOL capability depends on firmware, network hardware and OS power policy.

## Release versions

| Component | Version |
| --- | --- |
| Integration / source bundle | **0.5.1-beta.1** |
| Linux Host Agent | 0.4.0-dev.1 |
| SmartThings Edge Driver | 0.4.0-dev.1 |
| Windows Host Agent | 0.2.0-alpha.1 |
| Wire protocol | v2 |

**Maintenance scope:** Experimental community beta. No automatic updates, signed binaries, Windows MSI, DEB/RPM packaging or manufacturer certification are claimed.
