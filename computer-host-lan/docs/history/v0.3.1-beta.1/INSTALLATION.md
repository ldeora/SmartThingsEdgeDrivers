# Linux Host Agent v0.3.0 — installation and upgrade

**Preview, not a public stable release.** The working SmartThings Edge Driver is
still **v0.2.9**, compatible with agent protocol v1. Users should not create
custom capabilities or re-pair devices for an agent update.

## Requirements

- Linux with **systemd as PID 1**. OpenRC/SysVinit/containers without systemd
  are not supported by this installer.
- **Python 3.10+**; pure standard-library runtime, no pip install needed.
- Root privileges for installation; standard `shadow` user-management tools.
- Recommended: Avahi for `_linuxhost._tcp` mDNS. Without it the LAN driver can
  be configured using its manual-host fallback.
- TCP 8765 accessible **only on trusted LAN / from SmartThings hub**;
  multicast UDP 5353 as required. Installer NEVER edits firewall rules.
- Optional: `ethtool` and a WOL-capable Ethernet adapter.

### First, verify and preview (no root)

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
```

The dry run lists files that would be created/replaced; it modifies nothing.

### Initial monitoring-only installation

```sh
sudo ./scripts/install-agent.sh
```

This creates the restricted `linuxhost` service account, the systemd agent,
code in `/opt/linux-host-agent`, optional Avahi service record, and the
root-only rollback snapshot. It starts the read-only HTTP agent. The privileged
power-control helper/socket is **disabled by default**.

After installation:

```sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v1/info
sudo ./scripts/diagnose.sh
```

Never share the private HMAC control key or unredacted identity-bearing logs.

### Opt into shutdown/reboot/suspend

Only enable if using a **trusted LAN** and you have configured the matching
SmartThings device preference for your control key.

```sh
sudo ./scripts/install-agent.sh --enable-power
```

The key lives in `/var/lib/linux-host-agent/control-token`, owned by the
unprivileged service account and mode `0600`. Read it privately as root to set
the SmartThings key preference. **Never include the key in public bug reports.**

Disable the privileged power endpoint explicitly, without deleting the key:

```sh
sudo ./scripts/install-agent.sh --disable-power
```

### WOL metadata and persistence

Pin a specific Ethernet NIC if autodetection is ambiguous:

```sh
sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0
```

**This does not change existing WOL persistence.** Read-only inspection:

```sh
sudo ./scripts/configure-wol.sh --interface enp3s0
```

To explicitly configure persistent WOL, add `--configure-wol` to the installer
or run `sudo ./scripts/configure-wol.sh --interface enp3s0 --apply`. The script
recognizes existing per-MAC `.link` rules and does not override them. A
NetworkManager system configures only the selected connection. Some NICs and
kernels require root for `ethtool` WOL queries; this is not a hardware failure.

### In-place upgrade (from v0.2.2)

1. Copy/download the release from a trusted location; review checksum/signature
   when publishing infrastructure provides them. Do **not** execute `curl | sh`.
2. Run `./scripts/preflight.sh` and `./scripts/install-agent.sh --dry-run`.
3. Verify that the existing agent is active and record the current power/WOL
   settings. The installer **preserves existing power opt-in and interface
   override** unless explicitly changed.
4. Run `sudo ./scripts/install-agent.sh` or pass your existing power/WOL flags.
5. Record the **recovery snapshot path** printed by the installer.
6. Run `/v1/info`, then SmartThings Refresh, and test agent interruption before
   testing a power cycle.

This upgrade **does not delete** installation UUID, control key or existing
SmartThings device. It does not change distribution Python symlinks, firewall,
IP settings, network manager, or existing persistent WOL rules.

### Rollback (root)

The installer creates a 0700 backup directory and `0600` manifest. It attempts
an automatic rollback if file installation or systemd activation fails. On a
later problem, supply the exact snapshot path printed during installation:

```sh
sudo ./scripts/rollback-agent.sh --backup /var/backups/linux-host-agent/snapshot-EXAMPLE
```

This restores managed application files/systemd units and their earlier
service start/enable states. It never restores or deletes secrets or identity.
**Do not rollback a snapshot from an unknown source.**

### Uninstall (explicit)

```sh
sudo ./scripts/uninstall-agent.sh --confirm
```

Stops/disables the agent and helper, then removes only the files owned by this
manual installer. Leaves `/var/lib/linux-host-agent` (including UUID and key),
`linuxhost` account, rollback snapshots, persistent WOL `.link` rules, and
SmartThings device intact. No implicit destructive purge is provided.

### Compatibility and troubleshooting

- RHEL 9 typically needs a parallel Python 3.11+ installation. The installer
  selects it without altering the OS default Python or takes `--python /path`.
- Fedora/RHEL/openSUSE with SELinux enforcing require **additional testing of
  service/socket labels**. The installer does not change policy rules.
- If the service fails, run `journalctl -u linux-host-agent.service -n 50 --no-pager`
  and `systemctl status linux-host-agent.service`; redact host identifiers.
- If `curl /v1/info` works locally but SmartThings cannot reach the host,
  inspect firewall restrictions on TCP 8765 and Avahi/mDNS UDP 5353.
- A missing CPU temperature sensor is not a fatal installation error.
- WOL depends on hardware, BIOS/UEFI and NIC power settings, not just the agent.
- Do not remove the SmartThings device to troubleshoot an agent upgrade.
