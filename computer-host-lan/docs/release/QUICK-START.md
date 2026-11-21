# Computer Host LAN — quick start (v1.0.0-rc.2 candidate)

**Status: rc.2 is a source/CI candidate, NOT a published download.** Integration **1.0.0-rc.2**, Linux/Edge **0.4.6-rc.2**, Windows **0.2.7-rc.2**, protocol v2 unchanged. Once approved and published, obtain matching assets from the [versioned rc.2 release page](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2); the link is **not an availability claim**. Do not install transient CI artifacts. The latest published prerelease remains [v1.0.0-rc.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) (November 20, 2026, UTC), and [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1) remains the Windows hardware-tested rollback baseline.

**rc.1 is not equivalent to rc.2:** Published rc.1 predates PRs #56–#59 and **does not have the hardened Windows ProgramData/control-token checks** ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)). Avoid rc.1 authenticated power commands on a shared PC with untrusted local users: inspecting `%ProgramData%\ComputerHostAgent` cannot prevent its fresh-install race. The rc.2 source includes the fix, but **real Windows 11 acceptance remains pending**. Review [known rc.1 issues](../../SECURITY.md#known-issues-in-the-published-rc1) and [rc.2 notes](RELEASE-NOTES-v1.0.0-rc.2.md).

**Requirements:** A SmartThings hub with LAN Edge support; computer and hub on a trusted private LAN; mDNS/UDP 5353 for automatic discovery and TCP 8765 from hub to computer (or your configured port). Never forward the agent's HTTP port to the Internet.

## Windows 11 x64

1. **After rc.2 publication only**, download `computer-host-lan-v1.0.0-rc.2-windows-x64-unsigned-setup.exe` and `SHA256SUMS.txt` from the [same versioned release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2). Verify SHA-256, then start Setup as administrator. The installer remains **unsigned**; Windows may show a publisher/SmartScreen warning. Do not use the older rc.1 Setup to test the new security protections.
2. On **SmartThings hub**, confirm the detected hub. If discovery fails, use **Search again**, enter the hub IPv4, or deliberately choose **Advanced options → Allow connections from devices on my local network** (Private profile only).
3. Leave **Power management** off for initial monitoring. Follow the **Connect to SmartThings** screen. You can reopen these instructions from the Start Menu.
4. In SmartThings, use the [existing channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20), enroll your hub if necessary, install **Computer Host LAN** and choose **Add device → Scan nearby**. Do **not** delete or re-pair an already installed computer device.
5. Check CPU, memory, system disk, uptime and online state in SmartThings. Optional power commands require opt-in on the computer **and** the matching control key in SmartThings settings. Save work and keep physical access before testing.

**Public-network troubleshooting:** Windows inbound access is restricted to **Private** networks, including the LocalSubnet fallback. If the computer is on a Public network, the agent's local health test can pass while hub connections fail. Check `Get-NetConnectionProfile` and, only on a trusted home LAN, change the hub-facing network to **Private** in Windows Settings. Setup never opens Public access or changes the Windows network profile.

**Existing Windows installation:** Run the newer Setup.exe **over** the current installation, including ZIP/PowerShell installations. Do not uninstall first or remove `%ProgramData%\ComputerHostAgent`. Setup is designed to retain the UUID, secret, configuration, custom port and previous power preference. If Setup fails, preserve the rollback snapshot; use the matching ZIP's `Restore-WindowsAgentUpgrade.ps1` rather than deleting state. The Windows ZIP is a fallback, not the preferred installation route.

## Linux (systemd)

Download the **matching v1.0.0-rc.2 source ZIP only after publication**. Linux needs Python 3.10+, systemd and Avahi. From the extracted source directory:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info
```

The installer retains the existing installation identity, key and opt-in configuration. Linux power and Wake-on-LAN configuration are optional and hardware-dependent.

## Feedback and limitations

For one-round verification, use the [short RC checklist](RC-ACCEPTANCE.md). Report the actual **OS, agent version, Edge driver version and result** (PASS/FAIL/NOT TESTED), particularly initial Windows installer rendering, hub discovery/retry, in-place upgrade, service restart and SmartThings device continuity. A Windows 11/SmartThings hardware result is not equivalent to CI. **Do not share IP/MAC addresses, installation IDs or control keys.** Full instructions: [installation and recovery](../../INSTALLATION.md).
