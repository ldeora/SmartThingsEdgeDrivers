# Computer Host LAN — Linux installer Quick Start (planned rc.3)

**Not yet a published release.** The standalone installer is implemented on
main; the rc.3 candidate release workflow builds the executable. Final build
verification and physical qualification are pending.
Do not download/elevate an ordinary CI artifact or source build as a substitute.
For published rc.2, follow the [current Quick Start](QUICK-START.md).

## 1. Prepare your computer

Use a Linux x86_64 (amd64) computer with systemd, Python 3.10+ and Avahi for
automatic discovery. Keep your SmartThings hub and computer on a trusted
private network. TCP 8765 (or your configured agent port) must be reachable
from the hub, and local multicast DNS (UDP 5353) must be available. Do not
forward the agent port to the Internet. See
[Avahi and firewall troubleshooting](../../linux-installer/README.md#troubleshooting-discovery-and-connectivity)
for distribution-specific instructions. Actual tested distributions will be
listed with the release.

## 2. Download and verify the installer

Once rc.3 is published, open its fixed, versioned GitHub release from the
[project README](../../README.md). Download the Linux x86_64 installer and
`SHA256SUMS.txt` from that same release. The candidate asset is
`computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer`, with matching
`computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer.build-info.json`.
The final source SHA is recorded by the exact-source build. Do not use a
development or temporary test artifact.

In your download directory, calculate the SHA-256 of the downloaded installer:

```sh
sha256sum ./computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer
```

Compare the entire hash with the exact matching filename in SHA256SUMS.txt.
After verification, rename the file locally to `computer-host-linux-installer`
for the commands below (or use its full versioned filename). Stop if the hash differs or the release source
cannot be established. Check the release announcement and recorded source
commit through a trusted channel. The binary is planned to be **unsigned**:
a matching checksum checks bytes, not independent publisher identity.
Only execute a file from a release you trust. Keep it in a private download
directory and do not replace it between verification and execution.
Formal signing/independent attestation integration is deferred to v1.2;
the existing optional attestation workflow is not the ordinary release route.

## 3. Run Setup

As your ordinary user (do not prefix the executable with sudo):

```sh
chmod u+x ./computer-host-linux-installer
./computer-host-linux-installer
```

A clean host opens setup directly. On an existing installation choose
**1 — Upgrade**; for retained data choose **1 — Install / reinstall**. Confirm or enter
your hub's IPv4, or choose it later. Leave remote power at its default for
initial monitoring; an existing power preference is retained unless changed.
Review the plan and type **INSTALL** (or **REUSE** for eligible retained rc.2 state) only if you agree to the changes. The
wizard then requests administrator authorization. You can cancel before
consent. The installer does not change firewall rules, start Avahi or pair
a SmartThings device. On a new installation with a suggested wired adapter,
Configure Wake-on-LAN is selected by default. Existing installations default
to Keep. Hardware support is checked after authorization; if the adapter
does not support magic packets or the check is unavailable (for example
ethtool is missing), the agent installs without configuring WOL and shows a
warning. If the optional network policy cannot be reviewed on a fresh setup,
the review offers installation with WOL left unchanged. Install ethtool
if missing and run setup again to enable WOL.

For plain-text prompts, run `./computer-host-linux-installer -accessible`.
For a real read-only plan, use `./computer-host-linux-installer -live -preview`.
For a simulated wizard, use `-demo`. The read-only plan and simulated
wizard never elevate; the accessible installation wizard still requires
explicit consent and administrator authorization.

## 4. Connect to SmartThings

Refresh an existing Computer Host LAN device first; do not delete or re-pair
it. For first-time setup, enroll the hub with the
[driver channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20),
install **Computer Host LAN** and select **Add device → Scan nearby**.
Check CPU, memory, disk, uptime and host status. If discovery fails, follow
the completion screen's network guidance.

Remote power is optional and requires opt-in on the host and in SmartThings.
Only if needed, retrieve the private key using the completion instructions;
enter it in **Power control key (64 hex chars)** and turn on
**Enable shutdown/reboot/suspend**. Do not share the key. Save your work and
keep physical access before testing shutdown, reboot or suspend. Wake-on-LAN
depends on wired Ethernet, BIOS/UEFI support and the network. Test shutdown
from SmartThings and switch on again, then reboot and repeat. To enable
Wake-on-LAN later, choose maintenance **2 — Configure**, then change power
or WOL settings and select Configure in the Wake-on-LAN step. Use `-configure` to check or remove an
installer-owned WOL setting. Normal uninstall keeps WOL unless you separately
confirm its removal.

## 5. Upgrade or recover

To upgrade, verify the newer release and run it over the existing
installation, including an existing installation made by the published
rc.2 legacy shell installer. This in-place migration is intended to be
supported and must pass rc.3 physical acceptance before release. Do not
uninstall first or delete persistent state or the SmartThings device. Use `-recover` with the verified installer if recovery
is required; review and explicitly authorize recovery before another
installation. Use `-uninstall` for normal removal, which retains the
private identity/key and recovery material. See the
[installer documentation](../../linux-installer/README.md) for CLI repair,
recovery, and detailed troubleshooting. Report OS/version and redacted
results using the [RC checklist](RC-ACCEPTANCE.md); never share credentials.

### Reinstall after an rc.2 uninstall

If setup finds retained installation data without a current agent, it offers
reuse of your existing identity and control key. Review the plan and type
**REUSE** only if it is your previous Computer Host LAN v2 installation.
Keep your original private files and backups intact. If reuse is refused,
see [reinstall and start completely fresh](UPGRADE.md#start-completely-fresh). The installer checks
eligibility after authorization and refuses ambiguous or unsafe state; it
will not reset the identity or key. Refresh the existing SmartThings device
rather than creating a duplicate. Select remote power again if you want it;
use the existing control key. Existing WOL settings are kept by default.

### Restore an earlier local installation

Run `./computer-host-linux-installer -restore` as an ordinary user. Authorize
listing the private local backups, select the desired agent version, review
its saved service and power state, then type **RESTORE**. Latest backup
means the saved state before the most recent eligible operation, not
necessarily an older version. After an rc.2 uninstall, reinstall with
REUSE first; historical restore requires recognized v2 state. Older software can
have defects fixed in the current release. The installer saves the current
managed files and service state first, restores the selected backup, and
retains the current identity, key and persistent NIC WOL. A saved interface
pin can be restored. Unrecorded optional files stay unchanged. Refresh the
existing SmartThings device and test it before upgrading again. Use `-recover`
only for an interrupted operation. Local backups are not release signatures.
CLI users can review `cli backups` and then use `cli restore --backup NAME
--backup-digest DIGEST --confirm RESTORE` with the selected digest.

### Maintenance menu

Run `./computer-host-linux-installer` again as your normal user. The menu
uses fixed keys; options not shown do not apply to the observed state.

| Key | Action |
| --- | --- |
| 1 | Upgrade / install bundled version, or install / reinstall if absent |
| 2 | Configure power or WOL through setup, or separately check/remove installer-owned WOL |
| 3 | Repair using the bundled version (existing agent) |
| 4 | Restore an earlier eligible backup |
| 5 | Recover an interrupted operation |
| 6 | Inspect installation status, read-only |
| 7 | Uninstall agent (existing agent); keep private state and backups |
| 0 / Enter | Exit without changes |

Selecting a task is not authorization. Follow its separate confirmation.
Inspect does not verify the protected journal; use `cli status` for that.
All existing flags remain available. See [all maintenance journeys](UPGRADE.md).
