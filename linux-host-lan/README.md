# Linux Host LAN for SmartThings

**Closed beta candidate: v0.3.1-beta.1** · Linux agent **v0.3.0** · SmartThings Edge Driver **v0.2.9** · Protocol **v1**

A SmartThings LAN Edge Driver and a lightweight Linux agent that let you **monitor and control Linux computers from SmartThings** over a trusted local network. No separate cloud account, MQTT broker, or Python pip dependencies are required for the agent. SmartThings itself remains responsible for device presentation and events.

> **Beta status:** Gentoo with systemd has been validated on real hardware for monitoring, reboot, suspend/resume, shutdown and Wake-on-LAN. Cross-distribution installation, SELinux/AppArmor policies and different hardware are **not yet validated**. Start with monitoring-only mode, and test power operations only when you can physically recover the PC.

## What it does

- Main SmartThings **Switch**: Wake-on-LAN to turn on; authenticated graceful shutdown to turn off.
- Additional **Wake**, **Reboot**, and **Suspend** controls.
- Reports CPU temperature (when available), CPU %, RAM usage/installed RAM, root filesystem usage, system uptime, 1/5/15-minute load averages and host state.
- Automatically discovers an agent using Avahi/mDNS (`_linuxhost._tcp`), keeps a persistent host identity and handles transient agent/network failures.
- Runs the agent as an unprivileged Linux service; optional shutdown/reboot/suspend uses a restricted privileged helper and authenticated requests.

## Requirements

- A SmartThings hub supporting LAN Edge drivers, on the **same trusted LAN** as the Linux computer.
- Linux with **systemd as PID 1**, **Python 3.10+**, and root access for the installation script.
- **Avahi/mDNS** for normal first-time discovery. The current manual-host fallback is developer-oriented and requires editing/repackaging the driver.
- TCP **8765** from the hub to the host; mDNS UDP **5353** for discovery. Restrict network access to your trusted LAN/hub. No firewall changes are made automatically.
- For Wake-on-LAN: supported Ethernet hardware, firmware and persistent OS WOL configuration. Monitoring does not require WOL.

## Start here (Linux computer)

The public beta distributes **two parts**: the Edge Driver through the publisher's SmartThings beta channel and the Linux agent as a GitHub Release asset. **A channel invitation has not yet been published.**

Download the **Linux Host Agent Bundle** from the project's GitHub Release, verify its SHA-256 checksum, and extract it. From the extracted agent bundle:

```sh
./scripts/preflight.sh
./scripts/install-agent.sh --dry-run
sudo ./scripts/install-agent.sh                  # monitoring-only, safest first test
systemctl status linux-host-agent.service
./scripts/beta-report.sh                       # redacted support summary; review before sharing
```

The installer creates a restricted systemd service, makes a recovery snapshot, preserves identity/keys during upgrade, and **does not** modify firewall rules, existing network configuration or persistent WOL unless explicitly requested. Do **not** run `curl | sh`.

Power control is **opt-in**, after reading [SECURITY.md](SECURITY.md):

```sh
sudo ./scripts/configure-wol.sh --interface enp3s0          # example NIC; dry-run
sudo ./scripts/install-agent.sh --enable-power --wol-interface enp3s0
```

The generated control key must be configured privately in the device's SmartThings settings. Never attach or publish the control key, authentication headers or raw unredacted logs. The Linux agent does **not** automatically activate the privileged power helper in a clean monitoring-only install.

See [INSTALLATION.md](INSTALLATION.md) and the [closed-beta tester guide](docs/beta/START-HERE.md) for step-by-step instructions, rollback and uninstall.

## Project layout

| Directory | Purpose |
| --- | --- |
| `agent/` | Pure Python agent, privileged helper and systemd/Avahi unit templates |
| `edge-driver/` | SmartThings LAN Edge Driver, profiles and publisher-owned custom capabilities |
| `scripts/` | Installer, rollback, diagnostics, WOL configuration and release tooling |
| `tests/` | Portability, protocol, telemetry, security and installer regressions |
| `docs/beta/` | Volunteer onboarding, test checklist, compatibility and feedback guidance |
| `docs/development/` | Protocol, state model and engineering/release notes |
| `ci/` | **Inactive** GitHub Actions template to enable later at repository root |

The existing SmartThings Edge Driver can be packaged from `edge-driver/` by its publisher; end users **do not need to register custom capabilities**. These six `oceancircle09600.*` capabilities and their presentations are maintained by the publisher.

## Validation and support

The known-working hardware combination is Agent **0.3.0** plus Edge Driver **0.2.9** on Gentoo. The beta engineering suite has been run in a Debian 13 environment, but that is **not** a full Debian systemd installation or hardware validation. Other distro combinations must be verified by volunteers.

```sh
python3 -m unittest discover -s tests -q
python3 scripts/ci/smoke_agent.py
```

Development tests use `requirements-test.txt` (PyYAML); the production agent itself has no PyPI dependencies. Feedback: use this repository's GitHub Issues (review [feedback guidance](docs/beta/FEEDBACK-AND-SUPPORT.md)) or the corresponding SmartThings Community thread once published. Run `scripts/beta-report.sh` and inspect the result before sharing.

## License and publication

This project is distributed under the **Apache License, Version 2.0** ([LICENSE](LICENSE); SPDX identifier `Apache-2.0`). This license applies to the Linux Host LAN project subtree, not automatically to other directories in the parent SmartThingsEdgeDrivers repository. Third-party provenance and attribution still require review before public beta publication. See [license notes](docs/beta/LICENSE-DECISION.md) and [publication gates](docs/beta/PUBLICATION-GATES.md).

The beta release is intended for **trusted local networks only**. Do not expose TCP 8765 to the Internet.
