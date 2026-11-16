> **Historical v0.3.1-beta.1 beta document.** This page describes the previous Linux-only
> integration and is **not** a valid installation or protocol guide for
> v0.4.0-dev.1. Use root `README.md`, `PROTOCOL.md` and `INSTALLATION.md`.

# Installation and package decision for the beta

**Recommended beta distribution:** signed and checksum-verified source archive plus the audited offline systemd installer. Do not publish installable `.deb` or `.rpm` packages until their ownership, migration and lifecycle behavior has been validated on those distributions. The user should not need pip or a Python venv at runtime.

## Why not ship native packages immediately?

- The tested installer currently owns `/opt/linux-host-agent` and custom units in `/etc/systemd/system`. Native packages should use distribution-controlled paths such as `/usr/lib` and a vendor unit directory. A package must **refuse** to silently take over a manual installation.
- Both DEB and RPM need a package lifecycle (pre/post-install, removal, upgrade, clean and failure paths), ownership of the `linuxhost` account, and a way to keep UUID/key under `/var/lib/linux-host-agent` private across upgrades/removals.
- A package install must not silently enable privileged power management, modify the firewall or rewrite WOL settings. A separate administrative opt-in is necessary.
- On Fedora/RHEL, service handling and SELinux context restoration need distribution-specific integration. On Debian/Ubuntu use `dh_installsystemd` and relevant `debhelper` tools, not ad hoc `systemctl enable` calls in arbitrary maintainer scripts.

## Proposed layout

- Python source and helper under distro-approved vendor libraries (`/usr/lib`/`/usr/libexec`), **not** `/opt`.
- systemd unit files under vendor unit directory (typically `/usr/lib/systemd/system` or architecture-specific macro).
- `sysusers.d`/distribution-equivalent system account, no fixed UID/GID.
- `/var/lib/linux-host-agent` remains stable across manual and packaged variants, never deleted without explicit purge.
- Avahi service definition and optional WOL administrative configuration handled separately.

## Package gates

1. Stable license, source provenance and versioned tags.
2. Native package builds on official supported distro images.
3. Static metadata and content inspection; no hardcoded Python path without version checks.
4. VM tests with actual systemd PID 1: clean install, upgrade, downgrade, rollback, uninstall and reinstall.
5. Negative test: package installed on a host with `/etc/systemd/system/linux-host-agent.service` from manual installer must refuse or explicitly migrate.
6. SELinux/AppArmor and firewall tests where relevant; no broad permissions granted implicitly.
7. Sign build artifacts and publish hashes; source archive remains an installation alternative for Gentoo/Arch.

Official references:
- Debian `dh_installsystemd`: https://manpages.debian.org/unstable/debhelper/dh_installsystemd.1.en.html
- Fedora systemd packaging: https://fedoraproject.org/wiki/Packaging:Systemd
