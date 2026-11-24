# Computer Host LAN — installation (protocol v2)

**Latest published prerelease: [v1.0.0-rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2)** (November 21, 2026 UTC; immutable source commit `72e4a99c4b2e8f958ce771152826319318d0d537`). Windows **0.2.7-rc.2**, Linux/Edge **0.4.6-rc.2**, protocol v2 unchanged. Obtain checksummed Windows/Linux release packages rather than transient CI artifacts. See [rc.2 notes](docs/release/RELEASE-NOTES-v1.0.0-rc.2.md) and [quick start](docs/release/QUICK-START.md). SmartThings driver assignment remains a separate action.

## Known differences between rc.1 and rc.2

The published rc.1 tag `5466ad0` predates PRs #56–#60. Published rc.2 contains the fixed Edge HTTP timeouts/Linux header deadlines (#30, partial #31), Windows native power error mapping (#33), Linux delayed helper calls (#44), hardened Windows ProgramData state/security (#32), and Private-only firewall warnings (#46). The **State security**, **Recovery after a security refusal** and **Windows network profile** sections describe rc.2, **not** rc.1 binaries. Physical Windows 11 rc.2 acceptance is still pending.

**If deliberately testing published rc.1:** On shared Windows PCs with untrusted local accounts, **do not enable authenticated power commands**. Check for unexpected pre-existing `%ProgramData%\ComputerHostAgent` ownership or files, but recognize that rc.1 also has a fresh-install race during directory creation, so the check is **not a complete mitigation**. Preserve all valid state and device identity. Prefer the published rc.2 release rather than trying to test missing rc.2 security improvements using rc.1. See [SECURITY.md](SECURITY.md#known-issues-in-the-published-rc1).

## Before installation

Use a trusted private LAN and a SmartThings hub that supports LAN Edge drivers. Allow mDNS discovery (UDP 5353) and hub-to-host HTTP TCP 8765. Never forward TCP 8765 to the internet. Host and hub must be able to reach each other; multicast separation or client isolation can prevent discovery. Install the new `computer-host-lan` driver, not the original `linux-host-lan` driver. Publisher-owned `oceancircle09600` capabilities must be registered by the publisher; testers should not register any.

## Windows 11 x64 — recommended graphical installer

**For rc.2 acceptance:** obtain the v1.0.0-rc.2 Windows x64 unsigned Setup.exe and `SHA256SUMS.txt` from the [published rc.2 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2). Verify checksums before running as administrator; a checksum beside an unsigned download is not a code signature. **Do not substitute rc.1 Setup when testing rc.2 security changes.**

1. Run Setup.exe. On the **SmartThings hub** page, select a discovered hub, retry **Search again**, or enter the hub's IPv4 manually. When discovery fails, the explicit **Allow connections from devices on my local network** option configures a Private-only LocalSubnet firewall rule; when discovery works, find this choice under **Advanced options**. It does not repair blocked mDNS between networks.
2. Choose whether to enable optional **Power management**. A new installation defaults to monitoring only. A Setup upgrade or conversion from the existing ZIP/PowerShell installation retains the previous power preference unless you change it.
3. On **Connect to SmartThings**, follow the [driver channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20): sign in, enroll your hub if needed, install **Computer Host LAN** under **Available Drivers**, then use **Add device → Scan nearby** in SmartThings. These instructions remain accessible from the Start Menu.
4. If power was enabled, the optional **Power control key** page offers Show/Hide and Copy. Enter that private 64-character key in the SmartThings device's `controlKey` setting, and enable `allowPowerCommands`. Keep it confidential.
5. Verify the service using `Get-Service ComputerHostAgent` and check `http://127.0.0.1:8765/v2/metrics` (replace 8765 if you configured another port). Test reboot/suspend/shutdown only with saved work and physical recovery available. Windows shutdown and reboot are graceful: the agent does not force applications closed, and an unsaved-work prompt can keep shutdown pending until someone responds at the console. A successful SmartThings acknowledgement means Windows accepted the native request, not that the PC has powered off or restarted.

**Windows network profile:** Setup and the PowerShell installer create a **Private-profile-only** inbound firewall rule, scoped to the selected hub IP or explicitly selected LocalSubnet fallback. If the interface used to reach the hub is classified as **Public**, SmartThings may fail to connect even though `http://127.0.0.1:8765/v2/health` works locally. Review the relevant profile with `Get-NetConnectionProfile`; only for a genuinely trusted home network, use **Windows Settings → Network & internet → Properties → Network profile type → Private** (the exact UI wording varies). Do not switch untrusted networks to Private and do not disable the firewall. A Public-profile warning is diagnostic only; Setup never changes network classification or broadens access to Public.

**State security:** A new state directory is created with its protected access list in the directory-creation operation; it is never exposed first with the inherited ProgramData permissions. Existing state is checked before use, including ownership, allow rules and reparse points. The directory and control-token must be owned by an administrator or SYSTEM; their DACLs may additionally grant the exact ComputerHostAgent service SID the access it needs. LocalService and that exact service SID are accepted as owners only for agent-created state files; arbitrary service SIDs are never trusted. Unsafe state is refused rather than silently adopted or rotated.

**Recovery after a security refusal:**

- **First installation / confirmed orphan:** If this PC has never had Computer Host LAN installed, first confirm that no `ComputerHostAgent` service or previous SmartThings device identity needs to be preserved. Inspect `%ProgramData%\ComputerHostAgent`. If it is clearly an untrusted folder planted before the first installation and contains no legitimate state, an administrator may remove that folder and retry Setup. Do not use this route for an existing installation.
- **Existing installation:** Do not delete the state directory or `installation-id`; losing that UUID can create a second SmartThings device. Have an administrator inspect and restore the expected owner and access rules before retrying. If an untrusted account could read or modify `control-token`, treat the key as compromised: disable `allowPowerCommands` on the SmartThings device and power control on the host while investigating. After restoring the directory's security and stopping the service (`Stop-Service ComputerHostAgent`), deliberately remove only the compromised `control-token`, rerun Setup with Power management enabled to generate a new key, and enter that new 64-character value in the device's `controlKey` setting. Re-enable `allowPowerCommands` only after both sides use the new key. The installer never rotates a key automatically.

**Upgrading:** Launch the new Setup.exe over the existing ZIP- or Setup-installed agent. Do not first uninstall, delete the SmartThings device or purge `%ProgramData%\ComputerHostAgent`. Inno Setup preserves the installation ID, control token, custom `appsettings.json` and previous power selection. Normal removal through Windows **Installed apps** removes the service, application files and firewall rule, but intentionally retains ProgramData state. Windows ARM64 is not supported by this x64 installer.

### Fallback: ZIP and elevated PowerShell

If graphical Setup fails, download the version-matched **Windows x64 unsigned ZIP** from the same release, verify its checksum, extract it, and run PowerShell **as Administrator** from the extracted directory:

```powershell
$hubIPv4 = '192.168.1.20'  # Replace with your actual SmartThings hub IPv4
.\scripts\Verify-Package.ps1
.\scripts\Install-WindowsAgent.ps1 -WhatIf
.\scripts\Install-WindowsAgent.ps1 -HubIPv4 $hubIPv4
Get-Service ComputerHostAgent
Invoke-RestMethod http://127.0.0.1:8765/v2/metrics
```

Omit `-HubIPv4` to allow LocalSubnet on Private Windows profiles. **Unlike Setup.exe, PowerShell upgrades require `-EnablePower` again if you want to retain remote power actions.** Without that flag, the script disables them; persistent identity and key remain unchanged. Private key inspection: `Get-Content "$env:ProgramData\ComputerHostAgent\control-token"`. For the script installation use `.\scripts\Uninstall-WindowsAgent.ps1` without `-PurgeState` when preserving your identity.


## Linux (systemd) — published rc.2 only

**Version boundary:** the commands below apply only to the immutable
published rc.2 source ZIP, not a checkout of main or a development source
archive. Current development source refuses legacy mutation commands.
An authenticated standalone installer is planned for the next release;
no attested release is available yet. Do not elevate source scripts or
substitute an unsigned CI artifact.

Requires Python 3.10+, systemd as PID1, Avahi/mDNS for automatic discovery and administrator rights to install. From the *matching* Computer Host LAN source directory:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info
avahi-browse -rt _computerhost._tcp
```

Power control is separate and opt-in in the published rc.2 package: `sudo ./scripts/install-agent.sh --enable-power --wol-interface YOUR_ETHERNET_INTERFACE`. The legacy `--configure-wol` option also applies only to published rc.2; current development source refuses it and does not change persistent WOL configuration. Keep the key in `/var/lib/linux-host-agent/control-token` private. Read [Linux parity acceptance](docs/development/LINUX-PARITY-ACCEPTANCE.md) before physical tests.

The earlier Linux Host LAN uses protocol v1 and a different discovery
namespace; do not install it alongside the new agent on the same listener.
There is no automatic v1 migration. Retain the old SmartThings device, ID
and key until a dedicated migration is available.

### Development source and intended v1.0 cutover

The source scripts are now read-only diagnostics or explicit refusals.
Use `./scripts/preflight.sh` and `./scripts/install-agent.sh --dry-run`
as an ordinary user for source inspection only. The legacy plan is
informational, not the protected controller's authorization or a guarantee
that installation will succeed.

The future independently verified Linux executable is the single supported
entry point for install, upgrade, repair, uninstall and interrupted
transaction recovery, through its wizard and explicit CLI. The CLI is
still development-only pending release qualification. See the
[consolidation contract](docs/development/LINUX-INSTALLER-CONSOLIDATION.md)
and [authentication procedure](docs/development/LINUX-INSTALLER-RELEASE-AUTHENTICATION.md).
Do not use a source script as a substitute.

Ambiguous retained state without a v2 ownership marker must be investigated;
automatic adoption and historical snapshot restore are not supported in
v1.0. Do not delete or regenerate the UUID/key or remove backups to bypass
a refusal. Persistent WOL configuration remains an administrator-managed
network setting; the source WOL utility now only previews possible changes.
The agent's WOL interface pin is distinct from persistent WOL configuration.

**Do not manually delete a pending protected journal or stage.** Interrupted
transaction recovery must use a verified compatible protected installer;
it is not a way to restore an arbitrary historical backup.

## Updates and caveats

A GitHub Actions artifact is temporary and is **not** a permanent published prerelease. Install only assets associated with a fixed release/tag and matching checksums. The published rc.2 packages are not authenticated by artifact attestation. The new release workflow is implemented but has not yet produced an accepted attested release. Keep applications saved before power tests. Do not use production or workplace computers for initial hardware experiments.

## Current upgrade and recovery guidance

The v0.5.5 Windows 11 tester confirmed a successful in-place GUI upgrade, preserved SmartThings device/settings, accurate CPU/RAM/disk statistics, service stop/restart recovery and functioning WOL. This does not validate the v0.5.6 hardening or the v1.0.0 RC on physical Windows hardware.

Run the version-matched newer Setup.exe over the existing installation. Do not uninstall, delete the SmartThings device or purge the persistent UUID and control token. Setup preserves the prior power preference; ZIP/PowerShell upgrades require -EnablePower again. Install only from a **published release** after checking SHA-256 hashes, not from temporary PR artifacts.

The published v0.5.6 beta introduced an interrupted-upgrade recovery option and checks health, version and existing identity before committing. Never delete the rollback snapshot or ProgramData files to bypass a failure. Keep a router DHCP reservation for the SmartThings hub. Review the [published beta release notes](docs/beta/RELEASE-NOTES-v0.5.6-beta.1.md) before any new hardware tests.

## v0.5.6 hub address maintenance and interrupted upgrade recovery

Reserve the hub's IPv4 in your router's DHCP configuration. To update an existing Windows firewall allow-list without reinstalling, open an elevated PowerShell prompt and run `& "$env:ProgramFiles\Computer Host Agent\Installer\Set-WindowsHubAddress.ps1" -HubIPv4 192.168.1.20`, replacing the example with the hub's actual canonical IPv4. The rule remains Private-profile only. A public or domain-connected network may require an explicit network-profile correction; do not make the rule Public by default.

An abandoned `Computer Host Agent.upgrade-rollback` folder must **never** be deleted casually. Interactive Setup can offer an explicit recovery attempt. If Setup cannot recover, use `Restore-WindowsAgentUpgrade.ps1 -Mode Restore` from the same-version Windows ZIP in an elevated PowerShell session; preserve the snapshot and host identity in ProgramData. Silent installers refuse abandoned snapshots without stopping the service.
