# Computer Host LAN — Linux installer Quick Start (planned rc.3)

**Not yet a published release.** The authenticated standalone installer is
under development. Do not download/elevate a CI artifact or a source build as
a substitute. For published rc.2, follow the [current Quick Start](QUICK-START.md).
Release preparation must replace the placeholders below with the independently
approved release tag and exact source commit; do not treat them as approval.

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

Once an eligible release is published, download the Linux executable
`computer-host-linux-installer` and its matching
`computer-host-linux-installer.sha256` from that versioned GitHub release.
Install GitHub CLI (`gh`) from a trusted distribution. Independently obtain
the approved tag and exact commit from the trusted release announcement or
verified source record; do not trust values merely supplied with the binary.
From the download directory, verify publisher/workflow identity and bytes:

```sh
gh attestation verify ./computer-host-linux-installer \
  --repo ldeora/SmartThingsEdgeDrivers \
  --signer-workflow ldeora/SmartThingsEdgeDrivers/.github/workflows/computer-host-linux-attested-release.yml \
  --source-ref refs/tags/EXPECTED_APPROVED_TAG \
  --source-digest EXPECTED_APPROVED_SOURCE_COMMIT \
  --signer-digest EXPECTED_APPROVED_SOURCE_COMMIT \
  --deny-self-hosted-runners \
  --predicate-type https://slsa.dev/provenance/v1 &&
sha256sum -c computer-host-linux-installer.sha256
```

Stop if either check fails or the approved source cannot be established. Do
not run an unverified executable, even for a preview. A checksum alone is
not publisher authentication. Keep the verified file in a private directory
and do not replace it between verification and execution. See the
[verification policy](../development/LINUX-INSTALLER-RELEASE-AUTHENTICATION.md)
for trust assumptions and limitations.

## 3. Run Setup

As your ordinary user (do not prefix the executable with sudo):

```sh
chmod u+x ./computer-host-linux-installer
./computer-host-linux-installer
```

The wizard detects an existing installation automatically. Confirm or enter
your hub's IPv4, or choose it later. Leave remote power at its default for
initial monitoring; an existing power preference is retained unless changed.
Review the plan and type **INSTALL** only if you agree to the changes. The
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
Wake-on-LAN later, run the installer again (upgrade/repair) and choose
Configure in the Wake-on-LAN step. Use `-configure` to check or remove an
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
Keep your original private files and backups intact. The installer checks
eligibility after authorization and refuses ambiguous or unsafe state; it
will not reset the identity or key. Refresh the existing SmartThings device
rather than creating a duplicate. Select remote power again if you want it;
use the existing control key. Existing WOL settings are kept by default.

### Restore an earlier local installation

Run `./computer-host-linux-installer -restore` as an ordinary user. Authorize
listing the private local backups, select the desired agent version, review
its saved service and power state, then type **RESTORE**. Older software can
have defects fixed in the current release. The installer saves the current
managed files and service state first, restores the selected backup, and
retains the current identity, key and persistent NIC WOL. A saved interface
pin can be restored. Unrecorded optional files stay unchanged. Refresh the
existing SmartThings device and test it before upgrading again. Use `-recover`
only for an interrupted operation. Local backups are not release signatures.
CLI users can review `cli backups` and then use `cli restore --backup NAME
--backup-digest DIGEST --confirm RESTORE` with the selected digest.

### Maintenance menu

Run `./computer-host-linux-installer` again as your normal user. An existing
installation opens Maintenance. Choose Upgrade, Configure, Repair, Restore,
Recover, Inspect, or Uninstall. Configure offers changing power or WOL settings
by rerunning setup with the bundled agent version, or checking/removing the
installer-owned WOL setting separately. Each operation still asks for its own
confirmation. Inspect is read-only; protected journal status remains available
through `cli status`. Restore shows the current installed file version (if
readable) and labels the latest eligible backup. For a fresh installation the
usual setup opens directly. All existing command-line flags still work.
