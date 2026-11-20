# Computer Host LAN — volunteer beta quick start

Candidate release URL (not yet published): https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.6-beta.1


**Upcoming beta: v0.5.5-beta.1** is being prepared after the stabilization merge, but is **not downloadable yet**. Continue using published v0.5.4-beta.1 until the [new release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) is explicitly published and the updated Edge driver has been assigned to the existing channel. [Candidate changes and upgrade instructions](RELEASE-NOTES-v0.5.5-beta.1.md).

**Current public beta v0.5.4-beta.1 (published 2026-11-19):** Download the host agent from the [official GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1) and install the Edge Driver through the [verified SmartThings channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). A Windows 11 Pro volunteer has confirmed graphical wizard installation and upgrade plus accurate monitoring in SmartThings; earlier testing also confirmed Suspend, Reboot, and Shutdown (Off); WOL and further platform coverage still need testers. Do not follow old `Linux Host LAN` beta guides for this project; those use protocol v1.

## Requirements

A LAN-capable SmartThings hub, private trusted LAN with UDP5353/mDNS (for discovery), TCP8765 from the hub to the host, permission to install a background service, and a computer that can be physically recovered. Windows 11 x64 testers should start with wired Ethernet; Linux testers need Python 3.10+, systemd PID1 and Avahi. Power tests are **optional**. Save work before any power testing.

## 1. Download and verify

For Windows 11 x64, prefer the **unsigned graphical Setup.exe** from the published [v0.5.4-beta.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.4-beta.1). Verify the SHA-256 using `SHA256SUMS.txt`. For Linux, download the versioned source ZIP. Windows ZIP/PowerShell installation continues as a fallback, not a deprecated method. The older [v0.5.3-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.3-beta.1) assets remain available for rollback.

## 2. Install monitoring only

**Windows:** Run the Setup.exe as Administrator, confirm a discovered SmartThings hub or enter its actual IPv4 address, and leave **Power management** disabled for your first test. If mDNS is blocked, use the manual IP field or the explicit local-network firewall scope option. After installation, the wizard shows **Connect to SmartThings**, and the guide is available later from the Start Menu. See [Windows Setup and PowerShell fallback](../../INSTALLATION.md). Existing ZIP installations can be upgraded directly by Setup without losing identity, key or power preference.

**Linux (systemd):** From the extracted source directory:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
curl -fsS http://127.0.0.1:8765/v2/info
avahi-browse -rt _computerhost._tcp
```


## 3. Install SmartThings driver and pair

Open the [ARoedl SmartThings Edge Drivers invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), sign in, accept, enroll your hub, install **Computer Host LAN** under **Available Drivers**, then use **Scan nearby**. The host is discovered as Linux or Windows using `_computerhost._tcp`. Verify switch ON, host status, CPU%, RAM usage/total/used/available, root/system filesystem usage/total/used/available and uptime. Linux adds CPU temperature (when available) and load averages; Windows does not.

If discovery fails, report network profile, multicast reachability and HTTP response (redact IP/MAC/UUID). Do **not** turn off the system firewall globally. The `hostOverride` preference does not perform initial pairing.

## Upgrading an existing beta installation

Keep the existing SmartThings computer device and preserve the host agent's identity; do not uninstall or purge state. For Windows, run the new Setup.exe directly over the installed beta; Setup retains the prior power choice, UUID, token and configuration. The script-based ZIP remains available if Setup fails. Linux: `sudo ./scripts/install-agent.sh` preserves existing power-control opt-in. Windows **PowerShell fallback only**: reinstall with `-HubIPv4` and **include `-EnablePower` if previously enabled**; unlike Setup.exe, the script otherwise disables power commands. Verify `/v2/metrics` now includes `memory_used_bytes`, `memory_available_bytes`, `disk_root_used_bytes` and `disk_root_available_bytes` and that both SmartThings **Memory** and **Root filesystem** sections show usage %, total GiB, used GiB and available GiB. A normal hub reboot resolved stale capability metadata on the publisher's test hub without re-pairing.

## 4. Recovery then optional power

Stop/start the agent service and verify SmartThings recovers without creating duplicates. For power testing, opt in with the installer and SmartThings setting **only after monitoring works**. Save all work, keep physical access, test **reboot**, **suspend → WOL**, and **shutdown → WOL**, in that order. An accepted command is not proof of successful hardware power transition. Windows Fast Startup, Modern Standby and S5 wake may fail.

## 5. Record results and remove

Use [the structured checklist](TESTER-CHECKLIST.md), then share [sanitized feedback](FEEDBACK-AND-SUPPORT.md). Windows collector: `.\scripts\Collect-WindowsDiagnostics.ps1`. Linux report: `./scripts/beta-report.sh`. Review output manually; never publish a control token, host UUID, IP or MAC.

Windows graphical-install removal: Windows **Installed apps**; ZIP/PowerShell removal: `.\scripts\Uninstall-WindowsAgent.ps1`; Linux removal: `sudo ./scripts/uninstall-agent.sh --confirm`. Both preserve selected state by default; intentional purges must be explicitly requested.
