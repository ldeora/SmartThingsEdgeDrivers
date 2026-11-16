# Computer Host LAN — volunteer beta quick start

**Public beta v0.5.1-beta.1:** Download the host agent from the [official GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) and install the Edge Driver through the [verified SmartThings channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). A separate SmartThings account successfully installed this driver; real Windows 11 host discovery and power remain beta test objectives. Do not follow old `Linux Host LAN` beta guides for this project; those use protocol v1.

## Requirements

A LAN-capable SmartThings hub, private trusted LAN with UDP5353/mDNS (for discovery), TCP8765 from the hub to the host, permission to install a background service, and a computer that can be physically recovered. Windows 11 x64 testers should start with wired Ethernet; Linux testers need Python 3.10+, systemd PID1 and Avahi. Power tests are **optional**. Save work before any power testing.

## 1. Download and verify

Obtain the matching host installer from the [permanent v0.5.1-beta.1 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) (not a temporary Actions artifact), verify its SHA-256 file and extract it locally. Windows x64 ZIP contains `publish/win-x64/`, `scripts/`, `docs/` and license. Linux source installer is separate. Both require the same `Computer Host LAN` Edge Driver.

## 2. Install monitoring only

**Windows:** open PowerShell **as Administrator** in the extracted folder, substituting your real hub IP for the example:

```powershell
$hubIPv4 = '192.168.1.20'  # example only
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/info
```

**Linux (systemd):** from the source root.

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
curl -fsS http://127.0.0.1:8765/v2/info
avahi-browse -rt _computerhost._tcp
```

## 3. Install SmartThings driver and pair

Open the [ARoedl SmartThings Edge Drivers invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), sign in, accept, enroll your hub, install **Computer Host LAN** under **Available Drivers**, then use **Scan nearby**. The host is discovered as Linux or Windows using `_computerhost._tcp`. Verify switch ON, host status, CPU%, RAM%, disk and uptime. Linux adds CPU temperature (when available) and load averages; Windows does not.

If discovery fails, report network profile, multicast reachability and HTTP response (redact IP/MAC/UUID). Do **not** turn off the system firewall globally. The `hostOverride` preference does not perform initial pairing.

## 4. Recovery then optional power

Stop/start the agent service and verify SmartThings recovers without creating duplicates. For power testing, opt in with the installer and SmartThings setting **only after monitoring works**. Save all work, keep physical access, test **reboot**, **suspend → WOL**, and **shutdown → WOL**, in that order. An accepted command is not proof of successful hardware power transition. Windows Fast Startup, Modern Standby and S5 wake may fail.

## 5. Record results and remove

Use [the structured checklist](TESTER-CHECKLIST.md), then share [sanitized feedback](FEEDBACK-AND-SUPPORT.md). Windows collector: `.\scripts\Collect-WindowsDiagnostics.ps1`. Linux report: `./scripts/beta-report.sh`. Review output manually; never publish a control token, host UUID, IP or MAC.

Windows removal: `.\scripts\Uninstall-WindowsAgent.ps1`; Linux removal: `sudo ./scripts/uninstall-agent.sh --confirm`. Both preserve selected state by default; intentional purges must be explicitly requested.
