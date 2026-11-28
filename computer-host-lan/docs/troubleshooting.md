# Troubleshooting

Use the [Windows](install-windows.md) or [Linux](install-linux.md) installer matching your release. Do not substitute development binaries.

## Hub or computer not found

Confirm computer and hub are on the same trusted LAN and that client isolation or VLAN rules do not prevent communication. Install Computer Host LAN, not the old Linux Host LAN driver. Windows Setup can retry hub search or accept the hub's IPv4 manually. In SmartThings, Scan nearby is for new devices only; refresh an existing device instead.

## Firewall and Avahi

The hub needs TCP 8765 (or the configured port) on the computer; discovery needs local UDP 5353/mDNS. Never forward the agent port to the Internet or disable firewall protections.

Windows PowerShell:

```powershell
Get-Service ComputerHostAgent
Get-NetConnectionProfile
Invoke-RestMethod http://127.0.0.1:8765/v2/health
```

Linux terminal:

```sh
systemctl status linux-host-agent.service
systemctl status avahi-daemon.service
curl -fsS http://127.0.0.1:8765/v2/health
avahi-browse -rt _computerhost._tcp
```

Use the actual configured port if different. A successful local health request does not establish hub reachability. Windows Setup opens a Private-profile rule scoped to the hub or explicitly selected LocalSubnet. Only change the network to Private if it is genuinely trusted. Linux does not automatically change firewall rules or start Avahi. Check the trusted LAN's firewall zone and allow agent TCP only from the hub where practical, plus the required local mDNS traffic. Verify Avahi is running and advertising; if the directory was absent at install time, install/start Avahi according to your distribution and repair the agent installation.

### Avahi / mDNS

Before installing the agent, check that the Avahi daemon is running:

```sh
systemctl is-active avahi-daemon.service
```

If Avahi is missing, install the daemon and browsing tools appropriate for
your distribution. Examples (choose only the applicable one):

- Debian/Ubuntu: `sudo apt install avahi-daemon avahi-utils`
- Fedora: `sudo dnf install avahi avahi-tools`
- Gentoo: `net-dns/avahi` (ensure the distribution's D-Bus and systemd
  integration is available).

On a trusted systemd host, if permitted by your local policy, enable and
start the installed daemon with
`sudo systemctl enable --now avahi-daemon.service`.
Install the prerequisites before running the agent installer: it only
installs the managed Avahi service file when `/etc/avahi/services` exists.
If you installed Avahi afterward, resolve any pending recovery first, then
rerun the verified installer. The interactive wizard automatically chooses
upgrade when it detects an existing installation. Alternatively, use the
documented `cli repair --confirm REPAIR` action with an already-authorized
noninteractive elevation provider (see [Linux CLI](install-linux.md#noninteractive-cli)). Do not delete the retained
identity or SmartThings device.

After installation, verify the agent advertisement on the local network:

```sh
avahi-browse -rt _computerhost._tcp
```

Look for your computer and its expected address/port, not just any
Computer Host LAN agent. A local result does not establish that the hub
can see it. Keep multicast DNS (UDP 5353) available on the trusted
hub-facing network; guest isolation, VLANs or multicast filtering may
prevent discovery. Do not expose mDNS to untrusted networks.

### firewalld and other firewalls

If firewalld is active, inspect the runtime configuration as administrator:

```sh
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --zone=ZONE --list-all
```

Replace `ZONE` with the zone that actually applies to the hub's traffic;
check the interface and any source-based zone assignments. Use the
agent's configured TCP port (default 8765) and the hub's actual IPv4.
For example, the following adds a **temporary, hub-scoped IPv4 rule**
for testing only. Replace both the example zone `home` and the reserved
documentation address `192.0.2.20` with your own values, and adjust the port
if necessary. Do not use this rule on an untrusted network.

```sh
sudo firewall-cmd --zone=home --add-rich-rule='rule family="ipv4" source address="192.0.2.20/32" port port="8765" protocol="tcp" accept' --timeout=5m
```

The rule expires after five minutes. If hub connectivity works, add
the same reviewed rule to the permanent configuration. Replace the zone,
hub IPv4 and port just as for the temporary rule:

```sh
sudo firewall-cmd --permanent --zone=home --add-rich-rule='rule family="ipv4" source address="192.0.2.20/32" port port="8765" protocol="tcp" accept'
sudo firewall-cmd --reload
```

Before reloading, review the permanent configuration and any unrelated
runtime-only rules: reloading replaces runtime policy with permanent policy,
which can remove other temporary rules and affect connectivity. Do not reload
until it is safe for your host. The temporary test rule is replaced by the
permanent rule, as intended. Verify hub connectivity again. Check runtime
and permanent policy separately; avoid copying unrelated runtime rules
into permanent policy. Reserve the hub's IP or update the rule if it changes.

Check mDNS separately on the trusted LAN (firewalld's `mdns` service may be
appropriate there). If using UFW, nftables or another firewall, apply
the equivalent hub-scoped rule using that firewall's own administration
tools. A missing firewalld warning does not mean the firewall is inactive
or that traffic is permitted. Do not disable the firewall, broadly open
the agent port or forward it to the Internet.

## IP address changed

A computer address change and a hub address change are different. Allow the driver to rediscover the computer; verify any manual host override still points at the correct host. If the hub's address changed, a hub-scoped Windows firewall rule may need an explicit scope update using Setup or [Set-WindowsHubAddress.ps1](install-windows.md#powershell-fallback). Update any Linux hub-scoped firewall rule as well. A router DHCP reservation for the hub helps prevent this. Never delete the device or reset its key to repair an address change. If recovery does not occur, report the elapsed time and exact versions.

## Power command refused or generic app error

A refused command may produce a generic network/server error in SmartThings even while monitoring works. Not every error means refusal. Check host power opt-in, Enable shutdown/reboot/suspend in device settings, and that Power control key contains the matching 64 hexadecimal characters copied from the computer's installation. A missing or malformed key in the device preferences can prevent a power request; a missing/unsafe Windows host token can leave monitoring available with power disabled. After reusing rc.2 state, enable remote power again during setup if it was previously enabled. After host power is enabled, SmartThings may take time to recognize the newly available actions (about one minute observed on Gentoo, not a guaranteed maximum). Refresh the device and allow metadata to update before testing a new deliberate command; never repeat an earlier request whose acceptance is uncertain. Do not publish the key. Check redacted logs for refusal or transport failures.

See [Host Status and the switch](smartthings.md#host-status-and-the-switch). An accepted request is not proof of completed shutdown or reboot. Never replay a power command that might already have been accepted. Save work and keep physical access.

## Metrics missing

Refresh the existing device and check service health using the commands above. Confirm the installed agent and driver versions. Some fields are optional on older protocol-v2 agents. Windows does not fabricate CPU temperature or Linux load averages. Linux filesystem available space may exclude reserved blocks; Used + Available need not equal Total.

## Sleep or Wake-on-LAN not working

Check the NIC's wake support, firmware settings, supported sleep states, and network connectivity. On Windows, `powercfg /a` reports supported sleep states. On Linux, `cat /sys/power/mem_sleep` can show available suspend modes. WOL is best effort; Modern Standby, hibernate, Fast Startup and S5 wake vary by device. On Linux, choose maintenance 2 → change power or WOL settings, then Configure on a wired adapter. Fresh setup suggests Configure for wired Ethernet, upgrades retain the existing policy. Ordinary-user ethtool may report permission denied; hardware support is checked after authorization. If ethtool is missing or support cannot be checked, the agent can install without WOL and shows a warning. Install ethtool if missing and retry setup. If a network policy or ownership conflict is reported, leave it unchanged and investigate NetworkManager or /etc/systemd/network. Windows NIC WOL remains manual. Verify that the running agent has supplied WOL metadata and retain physical recovery access. Do not assume every advertised power action succeeds on every host.

## Uptime looks too long (Windows)

The agent reports the time since Windows last really started, the same value as Task Manager (Performance → CPU → Up time). With Fast Startup, commonly enabled on Windows 11, "Shut down" can retain the kernel session, so the uptime continues; Restart resets it. Some network adapters cannot wake from this kind of shutdown. If Wake-on-LAN works from sleep but not after Shut down, try disabling Fast Startup (Control Panel → Power Options → Choose what the power buttons do).

## Installer refuses unsafe state or upgrade fails

Stop and preserve installation identity, credentials, rollback material and journals. Follow [upgrade and recovery](upgrade.md); do not purge state or delete a pending protected journal to bypass refusal. After rc.2 uninstall, use menu option 1 and REUSE before attempting historical restore. If reuse cannot be validated, seek support; a deliberate [completely fresh installation](upgrade.md#start-completely-fresh) creates a different SmartThings device and requires rebuilding routines. Never use that path simply to repair an upgrade.

## Reporting a problem

Report exact OS, agent and driver versions, symptoms, whether local health works, and redacted logs. Never share control keys, nonces, signatures, UUIDs, IPs or MAC addresses. See [security](../SECURITY.md).

### Collect diagnostics safely

- Windows: from the version-matched fallback ZIP, run
  ` .\scripts\Collect-WindowsDiagnostics.ps1 ` following its help. Review the
  collected report before attaching anything. `powercfg /a` is useful for
  sleep/wake issues.
- Linux: the version-matched source-only ZIP contains the read-only
  `scripts/beta-report.sh` (use `--port PORT` for a custom agent port).
  Do not elevate legacy source installation scripts. Read service status and
  relevant journal messages locally, and redact them before sharing.
- SmartThings: note the actual installed Edge driver version, hub firmware,
  platform and elapsed time. Debug logging is optional; turn it off afterwards.
  Do not post unreviewed driver logs or screenshots.

Report ordinary bugs in the [issue tracker](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose)
or the [Community discussion](https://community.smartthings.com/t/st-edge-computer-host-lan-bring-windows-and-linux-computers-into-smartthings-public-beta/312605).
For security concerns use the private reporting procedure in [SECURITY](../SECURITY.md).
See the [volunteer checklist](testing.md) for useful test cases.
