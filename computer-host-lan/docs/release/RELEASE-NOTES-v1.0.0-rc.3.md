# Computer Host LAN v1.0.0-rc.3 — release candidate

**Candidate, NOT published by this preparation PR.** Intended release:
https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3.
The candidate tag/name and these notes are not evidence that the release exists;
their presence does not by itself prove a release has been published.
The currently published release is [rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2).
GitHub publication and SmartThings channel assignment are separate actions.

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
Maintenance menu options make these workflows discoverable.

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
The Windows service has a descriptive name/description.

**Edge and reliability:** The switch acknowledges accepted shutdown and
successful Wake transmission promptly while Host Status reflects the actual
observed/inferred state. Duplicate shutdowns and grace-period commands are
handled conservatively. Settled stopped/suspended status persists during
silence. HTTP requests have a four-second inactivity timeout and an
eight-second cooperative request budget; Linux and Windows add per-source
connection admission limits. Discovery prefers a responsive known matching
endpoint and confirms migration before updating WOL metadata or issuing power
requests. These measures improve robustness, not authentication.

## Intended release downloads

All packages are unsigned. The normal workflow builds two independent
Linux replicas with Go 1.25.14, linux/amd64, CGO disabled and trimmed paths,
checks exact VCS revision, compares bytes and emits matching build metadata.

- `computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer`
- `computer-host-lan-v1.0.0-rc.3-linux-x64-unsigned-installer.build-info.json`
- `computer-host-lan-v1.0.0-rc.3-windows-x64-unsigned-setup.exe`
- `computer-host-lan-v1.0.0-rc.3-windows-x64-unsigned.zip`
- `computer-host-lan-v1.0.0-rc.3-source.zip`
- `computer-host-lan-v1.0.0-rc.3-documentation.zip`
- `SHA256SUMS.txt`

Verify the full SHA-256 of each downloaded asset against the same versioned
release's checksum manifest. Check the trusted release announcement/source
commit; a checksum does not authenticate publisher identity. Do not run
ordinary CI artifacts or elevate development source scripts. Formal signing
and independent attestation integration are deferred to v1.2; applicable
redistribution obligations remain.

## Install or upgrade

See the [Linux Quick Start](LINUX-INSTALLER-QUICK-START.md),
[Windows Quick Start](WINDOWS-QUICK-START.md), [maintenance journeys](UPGRADE.md)
and [troubleshooting](TROUBLESHOOTING.md) in the source/documentation package.
Windows Setup should be run over the existing installation. Linux uses the
standalone installer, with maintenance option 1 on an existing computer.
Preserve private credentials, settings and the existing SmartThings device.
Do not uninstall first or delete/re-pair for ordinary upgrades. Each new
computer gets a separate identity. Power actions remain opt-in.

## Known limitations and acceptance

- WOL depends on wired NIC, firmware, network and OS power state. The installer
  cannot promise wake from every sleep/shutdown state. Windows NIC WOL setup
  is manual. Linux refuses ambiguous administrator network policy.
- Windows first-search UI painting needs physical confirmation; ARM64 is
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
- Existing protocol-v2 agents are intended to coexist; mixed-version actual
  hub acceptance remains required. No forced simultaneous upgrade.

Exact-final-main CI, reproducible installer build, downloaded asset validation,
Gentoo upgrade/restore/reinstall and WOL, a second rc.2 reuse test, NetworkManager
physical WOL, Windows 11 acceptance and private-channel mixed-version testing
remain to be recorded. See [rc.3 readiness](RC3-READINESS.md).
No physical PASS or public deployment is implied by candidate preparation.
