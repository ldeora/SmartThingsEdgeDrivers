# Compatibility evidence (as of 2026-11-15)

**Evidence legend:** Real hardware = agent + SmartThings hub + power actions actually verified. Source smoke = unit tests, installer preview and loopback HTTP in a container environment; no systemd PID 1 nor physical power management. Planned = workflow added but not executed.

| Target | Evidence | Remaining questions |
| --- | --- | --- |
| Gentoo Linux, systemd 261 | **Real hardware PASSED**, Python 3.14, Agent 0.3.0, Edge 0.2.9 | Rollback on real system, adverse network tests |
| Debian 13 | **Source smoke PASSED** on Debian 13 container, Python 3.13 | systemd PID 1, Avahi, app pairing, physical power, firewall |
| Debian 12 | **CI planned** | package prerequisites, full lifecycle |
| Ubuntu 24.04 LTS | **CI planned** | netplan manager variant, firewall, Avahi |
| Ubuntu 26.04 LTS | **CI planned** | netplan/networkd/NM, service startup |
| Fedora 43 / 44 | **CI planned** | SELinux enforcing, firewalld, NetworkManager |
| RHEL 9 / Rocky / AlmaLinux | Compatibility investigation | Explicit Python 3.11/3.12, SELinux, support lifecycle |
| RHEL 10 / compatible | Compatibility investigation | SELinux, installation, network/firewall |
| Arch Linux | Compatibility investigation | rolling updates and minimal-system dependencies |
| openSUSE 16/Tumbleweed | Compatibility investigation | network manager, MAC policies, packaging |

The source smoke CI matrix in `.github/workflows/tests.yml` is **not executed by merely publishing this archive**. GitHub Actions results or other evidence must be collected after the repository is set up. `systemd-analyze verify` is a static unit check; it is not the same as starting a service under PID 1. Physical WOL testing needs a compatible NIC, firmware configuration and an external hub/device; containers generally cannot provide that evidence.

The initial closed beta should use a small volunteer group across at least Debian/Ubuntu and Fedora as well as Gentoo. For each target, require a clean install, source smoke, trusted-LAN discovery, state recovery, upgrade/rollback and—where supported—hardware WOL/power testing. Do not mark a distribution “supported” solely from passing Python tests.
