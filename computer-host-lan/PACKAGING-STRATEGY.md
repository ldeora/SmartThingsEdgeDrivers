> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# Packaging policy and installation strategy — decision proposal

## Decision

**Two-stage distribution model**:

1. **Technical alpha/closed beta:** signed/tagged source release ZIP or tarball
   and one auditable offline installer. No `curl | sh`, no dependency downloads,
   no hidden package-manager changes, no auto WOL/firewall modification.
2. **Public beta/GA:** distribution-native DEB and RPM packages generated from
   the **same versioned source tree**, with an installer fallback for Gentoo,
   Arch and testers. Native packages must not overwrite the prior manual install
   unexpectedly; implement detection and an explicit migration path.

The SmartThings Edge driver is a separate distribution artifact installed
through the developer's published SmartThings Edge channel. End users should
not need a SmartThings CLI developer account or custom capability registration.
Per SmartThings documentation, a tester accepts the developer's channel
invitation link and installs the driver to their selected hub; do not invent
or publish the invitation URL until the beta channel has been configured.

## Why packages are worthwhile

- Dependency validation (Python 3.10+, systemd, Avahi as optional/recommended).
- File ownership and clean uninstall, package inventory, upgrade/rollback.
- Conventional distro service management, system user creation and package
  verification. Native packaging also handles SELinux/AppArmor integration
  more reliably when appropriately authored and tested.

## Recommended package layout

```
/usr/libexec/linux-host-agent/linux_host_agent.py   # or /usr/lib/linux-host-agent on Debian
/usr/libexec/linux-host-agent/power_helper.py
/usr/lib/systemd/system/linux-host-agent.service
/usr/lib/systemd/system/linux-host-agent-power.socket
/usr/lib/systemd/system/linux-host-agent-power.service
/usr/lib/sysusers.d/linux-host-agent.conf
/usr/lib/avahi/services/linux-host-agent.service
/etc/linux-host-agent/                        # administrator configuration, not secrets
/var/lib/linux-host-agent/                    # StateDirectory: UUID/key; preserved on upgrades
```

Path conventions differ across distributions; use build-system macros and the
appropriate policy directories. Keep the manually installed `/opt` layout
until a migration plan is tested. The agent and HMAC key should have a stable
state directory regardless of packaging method.

## Package behavior

- Installer prompts/opt-in are separate from package install: **no default
  remote power socket** and **no system-wide firewall changes**.
- Do not enable services unconditionally in RPM post-install scripts;
  follow distribution systemd preset policies.
- Create the account using supported `sysusers.d` or distribution helper;
  do not hardcode UID/GID.
- Keep the state directory (UUID and HMAC key) across in-place upgrades and
  normal package removal; offer explicit destructive purge only.
- Provide verified, documented downgrade and migration from `/opt` scripts.
- Never publish personal installation token, a host UUID or host MAC in packages.
- Produce checksums and signed releases using maintained CI credentials.

## Why we are not shipping untested DEB/RPM files yet

A file ending in `.deb` or `.rpm` can be generated locally without any actual
installation test. Doing so now would imply portability that has not been
proven. Test the systemd units, account provisioning, SELinux and uninstaller
behavior on target images first. Packaging should automate an established
installation design, not become a substitute for validating one.

## Further design questions

- Is a non-systemd agent desirable as a separate later project? (Currently no.)
- Should beta default to monitoring-only, with power control opt-in? (Yes.)
- Should manual and native packages share one updater? (No; one ownership per
  installation.)
- Should we support automatic updates? (Not during beta; use signed artifacts.)

Sources:
- https://systemd.io/PRESET/
- https://www.freedesktop.org/software/systemd/man/latest/sysusers.d.html
- https://fedoraproject.org/wiki/Packaging:Systemd

- https://developer.smartthings.com/docs/devices/hub-connected/enroll-in-a-shared-channel/
