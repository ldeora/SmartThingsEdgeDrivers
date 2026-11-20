# Computer Host LAN v0.5.6-beta.1 — consolidated installer and runtime hardening

**Status:** Release candidate source on review branch. **Do not publish or distribute until all native Windows and Linux CI checks pass at the final merged commit and migration behavior is reviewed.** This is one combined follow-up to the independently tested [v0.5.5-beta.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.5-beta.1); no intermediate v0.5.5-beta.2 is planned.

## Versions

| Component | v0.5.6 candidate | Published v0.5.5 |
| --- | --- | --- |
| Integration | **0.5.6-beta.1** | 0.5.5-beta.1 |
| Windows agent | **0.2.5-beta.1** | 0.2.4-beta.1 |
| Linux agent | **0.4.4-beta.1** | 0.4.3-beta.1 |
| SmartThings Edge driver | **0.4.4-beta.1** | 0.4.3-beta.1 |
| Agent protocol | **v2 unchanged** | v2 |

## What's changed

- **Recoverable Windows upgrades:** Detect existing rollback snapshots before touching the running service; the wizard can request explicit restoration of an interrupted upgrade. A recovery script is shipped in the installer and ZIP. A bounded HTTP health check verifies protocol, runtime version and the original installation UUID before committing a successful upgrade.
- **Safer Windows hub IP handling:** Canonical IPv4 validation rejects ambiguous leading-zero forms. The wizard recommends a DHCP reservation. The included `Set-WindowsHubAddress.ps1` can update the Private-profile firewall's allowed hub IP without changing persistent identity or power-control preferences. Public network firewall access is **not** opened automatically.
- **Windows runtime resilience:** Validate available shutdown privileges before advertising power actions; retain HTTP monitoring even if privilege policies block remote power. mDNS registration failures no longer terminate monitoring and are retried with bounded backoff. WOL metadata refreshes on subsequent `/v2/info` requests and prefers physical NICs, retaining an explicit NIC override.
- **Identity and secrets:** Linux and Windows create new identities atomically to avoid partial files after interrupted first startup. Existing corrupt identity files are still rejected, never silently replaced. Windows service state and token ACLs are restricted using its own service SID rather than relying solely on the shared LocalService identity.
- **SmartThings state machine:** Keep bounded action context for late shutdowns and avoid treating one transient failed health poll as proof of resume. The visible status may recover to Running before the internal action context expires; no new capability or device identity is introduced.
- **Linux:** Conservative protection against conflicting existing per-MAC systemd `.link` files when enabling WOL, and fixed protocol/version reporting in `beta-report.sh`.
- **Release hygiene:** Aligned versions and expanded regression tests. The beta remains unsigned.

## Verified baseline versus new changes

On November 20 a Windows 11 Pro tester independently confirmed a successful v0.5.4→v0.5.5 graphical upgrade, existing SmartThings device retention, accurate CPU/RAM/disk metrics, Windows service recovery (Off/Unreachable → On/Running after normal polling), working Wake/Restart/Sleep controls, working WOL and Windows agent 0.2.4-beta.1. Those results validate **v0.5.5 on that tester's hardware**, **not** the new v0.5.6 modifications. The published v0.5.5 assets remain available for rollback.

## Upgrade and rollback precautions

Run the graphical Setup.exe on a physically accessible Windows 11 x64 test PC. **Do not uninstall the existing version, delete the SmartThings device or purge `%ProgramData%\ComputerHostAgent`.** The wizard checks for abandoned upgrade snapshots; approve restoration only if the snapshot belongs to this installation. For a blocked or incomplete upgrade, retain the backup directory and use `Restore-WindowsAgentUpgrade.ps1 -Mode Restore` from the Windows ZIP as Administrator. Do not delete the backup to bypass the safety check.

On Windows, keep the SmartThings hub's LAN address stable using a router DHCP reservation. If its IP changes, use the provided elevated `Set-WindowsHubAddress.ps1 -HubIPv4 <canonical IPv4>` script to update only the firewall allow-list; never broaden it to public Internet access. Authenticated power remains opt-in and constrained to trusted private networks. Power controls still represent requests, not guaranteed electrical power-state changes.

On Linux, update from the matching source ZIP using `./scripts/preflight.sh`, `./scripts/install-agent.sh --dry-run`, and `sudo ./scripts/install-agent.sh`. Retain persistent UUID and control token.

**SmartThings:** The changed Edge driver v0.4.4-beta.1 must be packaged and assigned to the *existing* Computer Host LAN driver/channel only after publication approval. Keep the same driver ID, component IDs, profiles and capability schemas.

The Windows installer and agent remain unsigned. Validate the release's SHA256SUMS and use Windows SmartScreen guidance. Native Windows x64 testing, actual Windows 11 upgrades, permissions, WOL, sleep and failure recovery remain explicit pre-release acceptance gates.
