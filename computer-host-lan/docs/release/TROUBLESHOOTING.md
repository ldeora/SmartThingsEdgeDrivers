# Troubleshooting — v1.0.0-rc.3

This guide is for v1.0.0-rc.3. See [detailed installation](../../INSTALLATION.md). Do not substitute development binaries.

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

Use the actual configured port if different. A successful local health request does not establish hub reachability. Windows Setup opens a Private-profile rule scoped to the hub or explicitly selected LocalSubnet. Only change the network to Private if it is genuinely trusted. Linux does not automatically change firewall rules or start Avahi; see [distribution-specific guidance](../../linux-installer/README.md#troubleshooting-discovery-and-connectivity).

## IP address changed

A computer address change and a hub address change are different. Allow the driver to rediscover the computer; verify any manual host override still points at the correct host. If the hub's address changed, a hub-scoped Windows firewall rule may need an explicit scope update using Setup. Never delete the device or reset its key to repair an address change. If recovery does not occur, report the elapsed time and exact versions.

## Power command refused or generic app error

A refused command may produce a generic network/server error in SmartThings even while monitoring works. Not every error means refusal. Check host power opt-in, Enable shutdown/reboot/suspend in device settings, and that Power control key contains the matching 64 hexadecimal characters copied from the computer's installation. A missing or malformed key in the device preferences can prevent a power request; a missing/unsafe Windows host token can leave monitoring available with power disabled. After reusing rc.2 state, enable remote power again during setup if it was previously enabled. Do not publish the key. Check redacted logs for refusal or transport failures.

Switch shows the commanded state; Host Status reports the observed or inferred state. An accepted request is not proof of completed shutdown or reboot. Never replay a power command that might already have been accepted. Save work and keep physical access.

## Metrics missing

Refresh the existing device and check service health using the commands above. Confirm the installed agent and driver versions. Some fields are optional on older protocol-v2 agents. Windows does not fabricate CPU temperature or Linux load averages. Linux filesystem available space may exclude reserved blocks; Used + Available need not equal Total.

## Sleep or Wake-on-LAN not working

Check the NIC's wake support, firmware settings, supported sleep states, and network connectivity. On Windows, `powercfg /a` reports supported sleep states. On Linux, `cat /sys/power/mem_sleep` can show available suspend modes. WOL is best effort; Modern Standby, hibernate, Fast Startup and S5 wake vary by device. On Linux, choose maintenance 2 → change power or WOL settings, then Configure on a wired adapter. Fresh setup suggests Configure for wired Ethernet, upgrades retain the existing policy. Ordinary-user ethtool may report permission denied; hardware support is checked after authorization. If ethtool is missing or support cannot be checked, the agent can install without WOL and shows a warning. Install ethtool if missing and retry setup. If a network policy or ownership conflict is reported, leave it unchanged and investigate NetworkManager or /etc/systemd/network. Windows NIC WOL remains manual. Verify that the running agent has supplied WOL metadata and retain physical recovery access. Do not assume every advertised power action succeeds on every host.

## Installer refuses unsafe state or upgrade fails

Stop and preserve installation identity, credentials, rollback material and journals. Follow [upgrade and recovery](UPGRADE.md); do not purge state or delete a pending protected journal to bypass refusal. After rc.2 uninstall, use menu option 1 and REUSE before attempting historical restore. If reuse cannot be validated, seek support; a deliberate [completely fresh installation](UPGRADE.md#start-completely-fresh) creates a different SmartThings device and requires rebuilding routines. Never use that path simply to repair an upgrade.

## Reporting a problem

Report exact OS, agent and driver versions, symptoms, whether local health works, and redacted logs. Never share control keys, nonces, signatures, UUIDs, IPs or MAC addresses. See [security](../../SECURITY.md).
