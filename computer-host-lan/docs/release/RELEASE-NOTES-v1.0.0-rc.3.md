# Computer Host LAN v1.0.0-rc.3 — release notes

**Upgrading? Run the new installer over your existing installation. Normal upgrades are designed to retain your device, settings, routines and key. Refresh the existing device rather than pairing again.**

This document describes v1.0.0-rc.3. [Versioned downloads](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3).
GitHub release availability and SmartThings channel assignment are separate actions.

| Component | Version |
| --- | --- |
| Integration | 1.0.0-rc.3 |
| Linux agent | 0.4.7-rc.3 |
| Windows agent | 0.2.8-rc.3 |
| Edge driver | 0.4.7-rc.3 |
| Local protocol | computer-host-agent v2 (unchanged) |

## What's new since rc.2

**Linux installer:** A standalone x86_64 executable replaces the legacy
mutating source scripts. Run it as your ordinary user; protected operations
require review and explicit authorization. Fresh setup, upgrade, repair,
uninstall and interrupted recovery share the protected transaction engine.
The new full-screen terminal interface provides a unified maintenance menu, setup wizard, inspection, explicit typed consent and structured results. Genuine administrator prompts run on the ordinary terminal, with input ownership restored before handoff. Plain accessible and machine CLI paths remain available. Historical restore and installer-owned WOL operations can require separate authorization for their protected read and change steps.

- Persistent wired Wake-on-LAN using NetworkManager or systemd .link policy,
  with reviewed settings and explicit installer-owned removal. Existing
  installations retain WOL by default. Missing ethtool or unsupported/unknown
  capability can leave WOL unconfigured without preventing agent installation.
- Reinstall after an rc.2 uninstall with explicit REUSE and validated local
  private state/backup evidence. Enable remote power again if needed.
- Restore an earlier eligible local v2 backup with RESTORE, taking a new
  before-state snapshot first. Preserve current identity, key and persistent
  NIC WOL. Unrecorded optional files remain unchanged.
- Normal uninstall retains the identity, key, backups and NIC WOL, unless
  installer-owned WOL is separately removed.

**Windows:** Validated existing hub/firewall scope and power preference are
preserved on upgrade, including the ZIP/PowerShell path. Setup offers a
keep-current-settings summary. Runtime private-state checks refuse unsafe
identity state; an unsafe or missing power token disables power rather than
resetting the key. DNS-SD asynchronous registration failures can retry.
The Windows service has a descriptive name/description. Setup uses clearer power wording, explains manual Wake-on-LAN setup, shows a fixed hub address tip and updates its status as the user changes the hub address or local-network choice. The Windows quick start includes illustrated pages.

**Edge and reliability:** The switch acknowledges accepted shutdown and
successful Wake transmission promptly while Host Status reflects the actual
observed/inferred state. Duplicate shutdowns and grace-period commands are
handled conservatively. Settled stopped/suspended status persists during
silence. HTTP requests have a four-second inactivity timeout and an
eight-second cooperative request budget; Linux and Windows add per-source
connection admission limits. Discovery prefers a responsive known matching
endpoint and confirms migration before updating WOL metadata or issuing power
requests. These measures improve robustness, not authentication.

**SmartThings device tile:** Linux and Windows profiles show Host Status rather than only On/Off while retaining the switch action, metrics and routine capabilities. The existing Linux device was physically tested without re-pairing. The Unreachable inactive colour is a separate account-level capability presentation update, not part of the driver installation.

## Release downloads

All packages are unsigned. The normal workflow builds two independent
Linux replicas with Go 1.25.14, linux/amd64, CGO disabled and trimmed paths,
checks exact VCS revision, compares bytes and emits matching build metadata.

- `computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer`
- `computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer.sha256` — executable checksum
- `computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer.build-info.json` — exact source, component versions, toolchain and digest
- `computer-host-lan-v1.0.0-rc.3-linux-x64-third-party-notices.txt` — licence texts of the Go modules and runtime compiled into the Linux installer
- `computer-host-lan-v1.0.0-rc.3-windows-x64-unsigned-setup.exe`
- `computer-host-lan-v1.0.0-rc.3-windows-x64-unsigned.zip`
- `computer-host-lan-v1.0.0-rc.3-source.zip` — **source only**, not an installer
- `computer-host-lan-v1.0.0-rc.3-documentation.zip`
- `SHA256SUMS.txt` — covers all distributable assets except itself

Verify the full SHA-256 of each downloaded asset against the same versioned
release's checksum manifest. Check the trusted release announcement/source
commit; a checksum does not authenticate publisher identity. Do not run
ordinary CI artifacts or elevate development source scripts. Formal signing
and independent attestation integration are deferred to v1.2; applicable
redistribution obligations remain.

## Install or upgrade

[SmartThings driver invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) — enroll your hub and install Computer Host LAN if needed. Refresh an existing device instead of pairing again.

See the [Linux Quick Start](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/docs/release/LINUX-INSTALLER-QUICK-START.md),
[Windows Quick Start](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/docs/release/WINDOWS-QUICK-START.md), [maintenance journeys](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/docs/release/UPGRADE.md)
and [troubleshooting](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/docs/release/TROUBLESHOOTING.md) in the source/documentation package.
Windows Setup should be run over the existing installation. Linux uses the
standalone installer, with maintenance option 1 on an existing computer.
Preserve private credentials, settings and the existing SmartThings device.
Do not uninstall first or delete/re-pair for ordinary upgrades. Each new
computer gets a separate identity. Power actions remain opt-in.

## Known limitations

- After enabling host power control, SmartThings may take time to recognize the newly available actions. About one minute was observed on Gentoo during qualification (#193); this is not a guaranteed upper bound. Refresh and check the host/device opt-in settings; do not retry an uncertain accepted power request. The metadata-refresh improvement is deferred.
- A refused power command can still show the generic SmartThings network or server error. Check host power opt-in and matching key; do not blindly retry a request with uncertain acceptance.
- Both platform binaries are unsigned. The normal Linux release workflow does not generate independent artifact attestation. SHA-256 checks bytes, not publisher identity. Do not bypass platform protections.
- Automated Linux WOL setup supports wired Ethernet only; Wi-Fi wake is not supported by this installer.
- WOL depends on wired NIC, firmware, network and OS power state. The installer
  cannot promise wake from every sleep/shutdown state. Windows NIC WOL setup
  is manual. Linux refuses ambiguous administrator network policy.
- Windows first-search UI painting, display scaling and the Windows device presentation need physical confirmation; ARM64 is
  cross-build-only, not an x64 Setup target. Linux container tests do not
  certify physical WOL or every distribution. Linux firewall/Avahi setup
  may require manual administration.
- Monitoring and discovery are unauthenticated on the trusted private LAN;
  HMAC protects power requests, not telemetry confidentiality. Restrict HTTP
  reachability to the hub where practical; never forward the port to the
  Internet. Shared-source limits, distributed saturation and DNS rebinding
  remain risks. A power acknowledgement is not proof of physical transition;
  do not retry an uncertain accepted request.
- Restore supports validated local installed-state v2 snapshots, not arbitrary
  imported backups. Interrupted recovery differs from historical restore.
  Backup pruning is deferred to v1.1. No automatic key rotation or pairing.
- Existing protocol-v2 agents are intended to coexist; no simultaneous upgrade is required by the protocol.


## Qualification

Earlier unpublished rc.3 builds passed scoped Gentoo installer and private-channel Linux tile tests. These results are not a claim that every final-release byte or platform has been qualified. Exact-source CI, Windows 11 hardware, a second supported Linux host, the account-level Unreachable colour and stable-release soak are tracked in the maintainer readiness record. See the release availability and separately verified channel assignment rather than treating this document as publication evidence.

## Help us test

Please share results for fresh installation, upgrading over rc.2 without
changing anything in SmartThings, uninstall/reinstall, wired Wake-on-LAN
after reboot, and multiple computers on the same hub. Save your work and
retain physical access before testing power. Include OS, exact agent and
driver versions, hub model/firmware and observed behavior.

Report in the Computer Host LAN discussion (find it using [SmartThings Community search](https://community.smartthings.com/search?q=Computer%20Host%20LAN))
or [GitHub issues](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/new/choose).
Linux: the source-only archive includes the read-only
[`scripts/beta-report.sh`](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/scripts/beta-report.sh)
diagnostics script. Windows: use `scripts/Collect-WindowsDiagnostics.ps1`
in the matching ZIP. Review output and redact private identifiers, network
addresses and credentials before sharing. See the [test checklist](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/docs/release/RC3-READINESS.md)
for maintainer qualification details.
