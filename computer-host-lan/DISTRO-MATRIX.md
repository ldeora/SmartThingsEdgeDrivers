> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# Linux Host Agent — distribution compatibility matrix

**Status: researched compatibility hypotheses, NOT successful installation claims.**

The current **agent requires Linux, systemd for its shipped service/helper,
Python >= 3.10**, and the Python standard library (no PyPI modules). The
current installer needs standard `useradd`, `getent`, `install`, and systemctl.
Avahi/mDNS is recommended, optional if the SmartThings manual-host list is set.
CPU temperature and WOL hardware support are optional. The Edge driver uses
IPv4 for automatic mDNS discovery and local HTTP polling.

| Distribution family (priority) | Version(s) | Python / networking notes | Testing requirement |
|---|---|---|---|
| Debian (P0) | 12, 13 | Python 3.11 / 3.13; networking varies; systemd | Package deps, Avahi, networkd/NM, firewall, daemon restarts |
| Ubuntu LTS (P0) | 22.04, 24.04, 26.04 | Python 3.10 / 3.12 / 3.14; Netplan can use networkd or NM | Desktop + server; verify mDNS/firewall and WOL |
| Fedora (P0) | 43, 44 | systemd + normally NetworkManager | SELinux enforcing; firewalld; NetworkManager WOL persistence |
| RHEL-compatible (P1) | RHEL/Rocky/Alma 9, 10 | **RHEL 9 defaults to Python 3.9 (unsupported)**; install Python 3.11 or 3.12 separately. RHEL 10 defaults to 3.12 | SELinux, alternative interpreter path, helper permissions, rpm deps |
| Arch (P1) | Rolling | systemd; networking stack user-selected | Minimal setup, missing optional packages, boot recovery |
| openSUSE/SUSE (P1) | Leap/SLE 16 | systemd; NetworkManager in 16-series; SELinux policies may apply | NetworkManager, firewall, SELinux, zypper dependencies |
| Gentoo (validated) | User's live system | systemd 261, Python >=3.10, systemd-networkd, Avahi; WOL `.link` | Live power cycle, recovery, telemetry and custom app capabilities passed |
| Raspberry Pi OS (P2) | Current 64-bit | Debian derived; Raspberry Pi NIC/thermal layout differs | ARM64; CPU sensor selection; WOL often not possible |

Version numbers reflect upstream distribution docs as of November 2026,
not automated machine installs. Package availability and default network
configurations may differ by edition, image and hardware.

## Cross-distribution automated checks

1. Standard-library agent API and HMAC tests on Python 3.10, 3.11, 3.12,
   3.13 and 3.14 (where interpreter runners exist).
2. CLI preflight/installer dry-run tests in disposable distro containers.
   A container can check dependencies and file layouts, **not** certify WOL,
   Avahi multicast, SELinux policy, or systemd startup unless systemd is
   actually PID 1 in the test environment.
3. Disposable VMs for Ubuntu 22.04/24.04/26.04, Debian 12/13, Fedora 43/44,
   Rocky 9/10 and openSUSE 16. Build test matrix with explicit PASS/FAIL and
   exact image version, not assumed compatibility.
4. At least two **real** external beta machines (one NetworkManager, one
   non-Gentoo distribution) for hub mDNS discovery and state transitions.
5. Test a clean install, an in-place upgrade from previous beta, rollback,
   uninstallation, Python default mismatch, disconnected network, denied
   firewall, IPv6-only network, and missing CPU sensors.

## Compatibility boundaries

- **Not claimed**: OpenRC, SysVinit, containers without systemd PID 1,
  Windows, macOS, FreeBSD, IPv6-only discovery, wake over Wi-Fi, or all NICs.
- WOL across S5 depends on motherboard firmware, NIC and link power settings.
- The system's own firewall should allow *only the SmartThings hub* access to
  TCP 8765, plus local multicast UDP 5353 as appropriate; no auto firewall edits.
- No installers should modify distribution system Python symlinks.

## Primary research sources

- https://www.debian.org/releases/trixie/
- https://ubuntu.com/developers/docs/reference/availability/python/
- https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/installing_and_using_dynamic_programming_languages/
- https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html/installing_and_using_dynamic_programming_languages/
- https://fedoraproject.org/wiki/Tools/NetworkManager
- https://documentation.suse.com/sles/16.0/html/SLE-comparison/
- https://www.freedesktop.org/software/systemd/man/latest/systemd.link.html
