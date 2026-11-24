> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. The `configure-wol.sh --apply` example below
> describes only the historical v0.2.10 utility. Current development source
> keeps the preview read-only and explicitly refuses `--apply`; do not elevate
> this command from a current checkout. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# Linux distribution portability — 0.2.10

## Supported by implementation

The *agent* is pure Python 3.10+ and reads Linux `/proc` and `/sys` directly.
No third-party Python modules. The *installer*, privileged power helper, and
Avahi/systemd units explicitly require **systemd**, standard Linux account
management (`useradd`, `getent`), an available Python 3 interpreter, and
optional `ethtool`/`udevadm` for WOL. It determines Python's executable path
rather than relying on `/usr/bin/python3`. This makes it suitable in principle
for mainstream systemd distributions, but no broad distro validation has
been performed.

Avahi is optional when manual discovery is configured in the Edge driver.
The agent can provide metrics without CPU temperature if no supported sensor
exists. Metrics are global host readings rather than cgroup-container metrics.

## WOL persistence (explicit opt-in)

```sh
./scripts/configure-wol.sh --interface enp3s0
sudo ./scripts/configure-wol.sh --interface enp3s0 --apply
```

- When run without root, `ethtool` may fail its netlink WOL_GET with
  `Operation not permitted` (CAP_NET_ADMIN). Both dry-run and diagnostics
  retry `ethtool --disable-netlink` for an ioctl read; if unavailable they
  report that WOL status could not be determined, rather than claiming the
  NIC lacks magic-packet support. `sudo ethtool IFNAME` is an independent
  confirmation. `--apply` always requires root.
- Active NetworkManager: modifies only its currently active connection UUID,
  sets `802-3-ethernet.wake-on-lan=magic` (takes effect fully at next
  connection activation), and immediately applies `ethtool wol g`.
- Otherwise: writes a per-MAC systemd-udev `.link` file in
  `/etc/systemd/network/`; does **not** restart networking; immediately
  applies `ethtool wol g`. Confirm its file is the first matching `.link`,
  and confirm `Wake-on: g` after reboot.
- Non-systemd and unsupported init/udev environments: currently unsupported
  by the installer and power helper. An OpenRC service and privilege model
  will need independent implementation and tests before claiming support.

Existing `.link` files (including earlier working WOL configurations) can
win lexical priority. Confirm with `networkctl status IFNAME` and
`udevadm test-builtin net_setup_link /sys/class/net/IFNAME` before assuming
our new file applies. No network routes, interface IP addresses or firewall
rules are modified by these tools.

## Known gaps

- Non-systemd init families and non-Linux OSes.
- SELinux/AppArmor variants require policy validation; no automatic
  protection weakening or firewall opening is performed.
- No container/namespace guarantee; interfaces and WOL may be unavailable.
- Multi-NIC hosts should pin the intended physical Ethernet interface via
  `--wol-interface`. Wi-Fi WOL is not assumed.
- Firmware, NIC driver, standby power and UEFI/BIOS settings determine whether
  WOL is preserved in S3 / S4 / S5; software cannot guarantee them.

## v0.2.11 preflight and Python selection

Run `./scripts/preflight.sh` before installation; it is read-only and checks
systemd, Python 3.10+, standard tools, network-manager services and optional
WOL tools. The installer checks Python before installing any files and prefers
`python3` only when it meets Python >=3.10; if necessary it looks for parallel
`python3.11`, `python3.12`, `python3.13`, `python3.14` or `python3.10` executables.
Use `--python /absolute/path` for a nonstandard installation. This supports
RHEL 9's common Python 3.9 default without changing the OS interpreter.

**Caution:** a passing preflight checks prerequisites, not the daemon's SELinux
policy, packaging, access from the SmartThings hub or wake-on-LAN hardware.
See `DISTRO-MATRIX.md` for the precise test matrix.
