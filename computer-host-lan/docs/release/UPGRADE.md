# Upgrade, reinstall and maintenance — planned rc.3

**rc.3 is not yet published.** Use the [published rc.2 instructions](QUICK-START.md)
until the matching release is available. The following workflows are implemented
on main; exact-candidate physical acceptance is pending. Use the
[Linux Quick Start](LINUX-INSTALLER-QUICK-START.md) or
[Windows Quick Start](WINDOWS-QUICK-START.md) to verify the matching package.
Do not elevate a development source archive or ordinary CI artifact.
Successful supported upgrades preserve the UUID, key, device and routines.
Never delete a working device or private state to repair an upgrade.

## Fresh installation on a new computer

Install using the platform Quick Start. Each computer has its own identity and
key; do not copy private state to another computer. Monitoring is the default.
On Linux, a suggested physical wired NIC defaults to Configure WOL; power
management is a separate opt-in. If the optional WOL check is unavailable the
agent can still install, with WOL left unchanged. Confirm the plan with INSTALL.
In SmartThings scan nearby once for each new computer. Check monitoring first.

## Add a computer alongside an existing one

The same Edge driver supports Linux and Windows protocol-v2 agents. Leave the
working device and its settings untouched. Install the matching agent on the
other PC, scan nearby and check that each device reports only its own metrics.
Enable power separately, with that computer's key. Older rc.2 agents do not
need a simultaneous update; mixed-version acceptance remains a release gate.

## Upgrade in place

Linux: run the verified standalone installer as your normal user and choose
**1 — Upgrade**. An existing rc.2 v2 installation is eligible for migration
without uninstalling. Keep power and WOL unless intentionally changing them.
Python 3.10+ is selected automatically; no elevated interpreter override.
Review and type INSTALL. Windows: run the newer Setup over the existing
Setup/ZIP installation. Keep valid current scope and power settings; select
Change settings if needed. Do not uninstall first. On both platforms preserve
custom configuration/port, UUID and key; refresh the existing device, test
metrics and a familiar routine, and check optional power. Verify actual
configured port and service health; do not assume 8765 on a customized host.

## Repair or recover a failed operation

On Linux choose **3 — Repair** for a normal reinstall of the bundled agent
version with the existing identity and key, review and type INSTALL. This is
not interrupted-transaction recovery. If a transaction is pending, choose
**5 — Recover** (or `-recover`), review and type RECOVER. Recovery rolls back
interrupted work or finishes terminal cleanup; it does not resume a historical
operation. If the protected helper/journal cannot be verified, stop and retain
all evidence; never delete journal, staging or backup files to force progress.
Windows: use Setup's recovery offer or the matching ZIP's
`Restore-WindowsAgentUpgrade.ps1 -Mode Restore` as documented in the
[installation guide](../../INSTALLATION.md). Restart Setup after recovery.

## Reinstall after an rc.2 uninstall (J5)

rc.2 removed the managed agent files, including its power and WOL interface
drop-ins, but retained the private state directory and backup. The persistent
NIC WOL policy is separate. On Linux run the rc.3 installer, choose
**1 — Install / reinstall**, review and type **REUSE** only if this is your own
previous Computer Host LAN v2 installation. The controller checks the state
layout, UUID/key, account, stopped services and private v2 backup evidence.
The backup is protocol evidence, not proof linking a particular key to it.
Enable remote power again during setup if you used it before; otherwise an
existing device with power enabled can show a generic refusal. Keep WOL by
default. Refresh the original device; no new key or re-pairing is needed if
continuity is verified. For the CLI: review `cli plan --action install` and
run `cli install --confirm REUSE` (add `--power enable` if intended).
If reuse is refused, preserve state and backups and seek support. Reinstall
with REUSE before trying historical restoration on this layout.

## Restore an earlier Linux backup

Choose **4 — Restore** or run `-restore` as ordinary user. Authorize listing
local private backups, select the saved version and review its service and
power state. Latest backup is the state captured before the newest eligible
operation; it may be the same version as the current one. The installed file
version is not runtime verification. Type RESTORE only for the chosen backup.
The installer backs up the current state first, restores recorded managed
files and services, keeps unrecorded optional files, and verifies continuity
of both credentials. Persistent NIC WOL remains unchanged; a saved agent
interface pin may be restored. An older version can have known defects.
Refresh the existing device and test; upgrade again when ready. An interrupted
restore is undone with Recover, not by choosing the historical backup again.

CLI: `cli backups`, then
`cli restore --backup NAME --backup-digest DIGEST --confirm RESTORE`.
Use the name and digest from the reviewed list, not an arbitrary path. Local
backup digests bind the selection, not release authenticity.

## Normal uninstall and reinstall after rc.3

Choose Linux **7 — Uninstall** or `-uninstall`, then type UNINSTALL. This
removes managed agent files/services but retains the identity, key, account,
ownership marker, backups and recovery helper. Existing NIC WOL normally
stays; only a separate REMOVE confirmation restores an installer-owned
setting. Later choose option 1 and INSTALL; a valid v2 marker avoids the
legacy REUSE step. Enable remote power again if desired. Windows Installed
apps likewise retains ProgramData state; run Setup again without purging.
Keep the SmartThings device if returning to the same installation. Verify
that the device resumes reporting rather than creating a duplicate.

## Start completely fresh (J8)

**Only if you deliberately want a new identity**, or recovery is impossible
and you accept losing device continuity. This is not a workaround for an
unsafe-state refusal. Record your routines, device settings and dependencies
first; disable power commands and save work. A new identity will create a
different SmartThings device, so routines and settings must be rebuilt.
Never share the old key or move state between computers.

Linux: complete the supported uninstall first (rc.2 users use their matching
published rc.2 uninstaller; rc.3 users use option 7 / UNINSTALL). If already
uninstalled, verify there is no active service or pending transaction before
proceeding. An administrator may then archive the intact
`/var/lib/linux-host-agent` directory to a new administrator-only location,
outside that path, **only after verifying it is the real local state directory
and not a symlink, mount or ambiguous/untrusted layout**. Keep the original
permissions and prevent access by the running service account through the
private archive's parent. Do not remove the owner marker, helper, journal,
backups, account or network settings. If quiescence or a safe archive cannot
be established, stop and seek support; there is no automated Linux purge
command. Do not move files while any installer or agent is running.

Windows: complete normal uninstall and retain an administrator-private backup
of the state if needed. The matching ZIP's documented uninstall script has an
explicit `-PurgeState` option for deliberate removal of ProgramData state;
use only after confirming the old service is stopped/removed and the
state path is legitimate. Never purge for normal upgrades.

Run the new verified installer normally. Confirm the new monitoring
installation works, then deliberately remove the old SmartThings device
and scan nearby to create the new device; rebuild its routines/settings.
If enabling power, configure the new private key. Do not restore an old
credential into the new installation. Historical backups do not establish
identity ownership; keep them private and do not use them to recover a
different installation. Treat any unexpected reuse prompt as a stop condition.

## Change power control or the agent's interface pin

On Linux choose **2 — Configure → 1 — Change power or WOL settings**;
this reruns setup using the bundled agent version, not a configuration-only
edit. Review Enable/Disable (Keep is the existing setting), the interface
choice and final INSTALL confirmation. The pin selects the agent's reported
WOL interface; it does not persistently enable NIC wake by itself. After
enabling power, use the existing key if valid and opt in on SmartThings.
After disabling, also turn off Enable shutdown/reboot/suspend in the device.
Windows: rerun Setup and Change settings; preserve valid scope. Do not
regenerate keys for normal configuration changes.

## Configure and test persistent Wake-on-LAN

Use wired Ethernet, firmware/BIOS WOL support and a trusted local network.
Linux Configure → change power or WOL settings → Configure in the WOL step
reviews a NetworkManager profile or per-MAC systemd .link rule before
authorization. Ordinary-user ethtool may not report capabilities; confirmed
unsupported or unavailable hardware is nonfatal, and unsafe or changed
policy is not overwritten. If ethtool is missing, install it and rerun setup.
Save work, retain physical access, shut down from SmartThings, switch on,
reboot and repeat. On Windows configure NIC/firmware WOL manually; sleep
and shutdown states depend on hardware. Linux Configure → check/remove
installer-owned WOL (or `-configure`) is separate from changing the agent;
REMOVE requires explicit consent. Independently configured settings are kept.
Normal uninstall preserves WOL unless separately authorized for removal.

## Mixed-version use and driver upgrade

Agent and Edge releases are separate. A driver update should preserve the
existing device network identity, preferences and routines. Test with an
unchanged rc.2 agent beside an rc.3 candidate, verify actual installed driver
version on a private test hub/channel, refresh both devices, check metrics,
reconnection and opted-in power. Do not move a public channel for testing.
If a candidate fails, follow the version-matched recovery guidance; do not
delete or re-pair devices. Publication and channel assignment are separate.

See [troubleshooting](TROUBLESHOOTING.md) for refusals and connectivity.
Report exact versions and redacted symptoms. Never publish identity, key,
MAC, private IP or authentication material.
