# Linux Host LAN v0.3.1-beta.1 — Closed beta

**Release type:** prerelease; source and installer are provided for technical volunteer evaluation.

**Included runtime:** Linux Host Agent 0.3.0, SmartThings Edge Driver 0.2.9, protocol v1. No runtime changes relative to the Gentoo-validated combination.

**Features:** LAN discovery through Avahi/mDNS; CPU, RAM, disk, uptime, load and CPU-temperature monitoring; hub-side Wake-on-LAN; optional HMAC-authenticated shutdown, reboot and suspend; recovery after agent interruptions; safe status reporting.

**Compatibility:** Gentoo/systemd hardware cycle verified. Other systemd Linux distributions are prospective testers only. Requires Python 3.10+. On RHEL 9 use a compatible parallel Python rather than overwriting system Python. SELinux/AppArmor, networking, firewalls and WOL capability vary by installation.

**Beta assets:** Linux Host Agent Bundle v0.3.1-beta.1 (contains Agent 0.3.0) as `.tar.gz` and `.zip`, project-only source archive, and matching `SHA256SUMS.txt`. Edge Driver is delivered to hubs by publisher-controlled SmartThings beta channel; no local CLI compilation necessary for end users.

**Safety:** trusted LAN only; monitor-only default; power testing only with physical recovery; no firewall or network configuration changes by default. No public Internet exposure.

**Installation:** see `linux-host-lan/INSTALLATION.md` or the included bundle's `INSTALLATION.md`.

**License:** Apache-2.0 (full `LICENSE` bundled with source and Linux agent). **Before publishing:** complete code provenance/attribution review, beta channel validation on an external account, distribution tests and security review.
