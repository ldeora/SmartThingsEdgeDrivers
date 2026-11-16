# [ST Edge] Computer Host LAN — Linux & Windows monitoring, Wake-on-LAN and power management (public beta)

I’m opening the first public beta of **Computer Host LAN**, a new SmartThings Edge integration that lets SmartThings discover and monitor Linux and Windows computers on the local network, and optionally perform authenticated power operations.

This is a separate project from my earlier **Linux Host LAN** driver. The existing Linux-only integration remains available and unchanged. Computer Host LAN uses a common protocol and one Edge driver for both platforms, with a small platform-specific agent installed on the computer.

### Supported platforms for this beta

| Platform | Current status |
| --- | --- |
| **Linux** (systemd, Python 3.10+) | Fully tested with my Gentoo computer and a real SmartThings hub; other Linux distributions need testers |
| **Windows 11 x64** | Self-contained agent, installer, and Windows Service verified in Windows CI; **real SmartThings discovery and power behavior need testers** |
| Windows ARM64 | Cross-compiled only; no ARM64 hardware validation, not a primary beta target |

The integration reports CPU utilization, memory and disk usage, uptime, and connectivity. Linux also provides CPU temperature and load values where available. Windows does not expose those Linux-specific measurements, so the SmartThings profiles are tailored accordingly.

The integration also supports Wake-on-LAN from the SmartThings hub and optional reboot, suspend and shutdown. These operations are deliberately **disabled by default**; monitoring works without enabling them. Reboot, sleep and shutdown behavior—and especially waking from different power states—depend on the computer’s hardware, firmware and network configuration.

### Download and install

**1. [Computer Host LAN v0.5.1-beta.1 — GitHub Release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1)**  
Download the appropriate package and verify it with `SHA256SUMS.txt`. The Windows x64 ZIP contains a self-contained executable, installer/uninstaller scripts, diagnostics, and instructions; no .NET SDK is required. The Windows binary is unsigned.

**2. [SmartThings Edge Driver channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20)**  
Sign in with your Samsung account, accept the invitation, enroll your hub and select **Computer Host LAN** under **Available Drivers**. This is my existing shared driver channel; you do not need to install the other drivers available there. The channel installation has already been verified with another SmartThings account.

**3. [Installation and first-test guide](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/main/computer-host-lan/docs/beta/START-HERE.md)**  
Install the host agent, check its local HTTP endpoints, then use **Scan nearby** in SmartThings. The hub needs to reach the host on TCP port **8765**, and mDNS/UDP **5353** must be available between them. No port forwarding or cloud service is needed.

### What I would particularly like to test

The main objective is to validate **Windows 11 with real SmartThings hubs**: does automatic discovery work, do CPU/RAM/disk/uptime values update correctly, does the Windows Service recover after interruptions, and does the correct profile appear in the SmartThings app? Linux results from Debian, Ubuntu, Fedora and other systemd installations are equally welcome.

If the monitoring portion works and you are comfortable testing power management, try reboot first, then suspend with WOL, and finally full shutdown with WOL. Please use a noncritical computer, save your work and make sure you have physical access. Successful authentication or HTTP acceptance does not mean a Windows power transition or subsequent wake is guaranteed.

### Reporting results

I’ve included a [structured test checklist](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/main/computer-host-lan/docs/beta/TESTER-CHECKLIST.md) and a [GitHub issue template](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose). You’re also welcome to share initial results here in the thread.

Please include your OS/version, hub model and firmware, Ethernet versus Wi-Fi, the relevant checklist item, and what worked or failed. Avoid posting IP or MAC addresses, installation IDs, SmartThings account/location IDs, raw logs or the power-control secret. The Windows package contains a sanitized diagnostics collector, but please review its output before uploading it.

The Linux implementation has already completed real-hardware SmartThings tests; the Windows agent builds and passes service/authentication tests on Windows runners. **This beta is intended to establish the remaining Windows 11 and wider Linux hardware compatibility**, not to claim that every sleep state or WOL configuration has already been verified.

Thanks in advance to anyone willing to test and report back!
