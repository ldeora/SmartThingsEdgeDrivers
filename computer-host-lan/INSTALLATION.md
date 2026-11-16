# Linux installation — Computer Host LAN v0.4.0-dev.1

**Development build: not yet verified on real SmartThings hardware.** This
installer does not install Windows components and does not migrate old devices.
Use the archived known-working `v0.3.1-beta.1` package until deliberately
performing a controlled test. Keep a local recovery path for any power tests.

## Prerequisites

Linux with systemd as PID 1, Python 3.10+, administrator privileges for
installation, Avahi/mDNS for automatic discovery, a SmartThings LAN-capable
hub on the same private/trusted network. Do not expose TCP 8765 to the Internet.
Allow mDNS (UDP 5353) between hub and host.

## First: preview everything

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
python3 -m unittest discover -s tests -q
python3 scripts/ci/smoke_agent.py
```

## Prepare SmartThings separately

* Register **new** publisher-owned generic capability IDs under
  `oceancircle09600`. Instructions: `edge-driver/custom-capabilities/REGISTER.md`.
  Reuse existing `oceancircle09600.linuxLoad` rather than recreating it.
* Package/install the renamed `computer-host-lan` Edge Driver in your test
  channel, and remove the old SmartThings device/old driver assignment.
* The hub **does not** automatically register custom capabilities from files.
* Do not use the old agent with the new driver, or the new agent with the
  old driver; the protocol and discovery namespace have both changed.

## Monitoring-only Linux installation

```sh
sudo ./scripts/install-agent.sh
systemctl status linux-host-agent.service
curl -fsS http://127.0.0.1:8765/v2/info | python3 -m json.tool
avahi-browse -rt _computerhost._tcp
```

The existing Linux systemd unit, unprivileged `linuxhost` account, state
folder, and restricted helper remain Linux-specific. Upgrades preserve the
persistent key/identity files and a rollback snapshot. The installer does
not change the firewall, network manager or WOL persistence automatically.

## Power control, only after monitoring is stable

```sh
sudo ./scripts/install-agent.sh --enable-power
sudo ./scripts/configure-wol.sh --interface YOUR_ETHERNET_INTERFACE
# WOL configuration changes require explicit --apply after inspection.
```

Set the device's opt-in power preference and 64-character key privately.
Never publish that key or a raw control-request header.

Test reboot and suspend/resume with physical recovery access, then test
shutdown/WOL only when WOL is known to be persistent and functioning.
The current Linux switch OFF still requests graceful shutdown.

## Rollback

The installer prints the restricted snapshot path. Restore one of its
legitimate snapshots using:

```sh
sudo ./scripts/rollback-agent.sh --backup /var/backups/linux-host-agent/snapshot-EXAMPLE
```

Rollback restores the managed agent and systemd/Avahi files, **not**
SmartThings device state or capabilities. Restoring only the agent creates
a protocol mismatch with the generic Edge Driver; restore the old driver
alongside the old agent if returning to v0.3.1.

The Linux installation helpers have not been renamed or rewritten to avoid
introducing unnecessary service lifecycle changes in this first refactor.
Uninstall is explicit: `sudo ./scripts/uninstall-agent.sh --confirm`.
The retained state directory is not automatically deleted.

Read `SECURITY.md` and `docs/development/LINUX-PARITY-ACCEPTANCE.md` before
end-to-end power testing.
