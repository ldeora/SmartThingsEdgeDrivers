# Computer Host LAN v1.0.0-rc.2 — release candidate

**Status: release-candidate source for review and CI; NOT published or assigned to a SmartThings channel.** When approved and published, the release page will be [Computer Host LAN v1.0.0-rc.2](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2). A reference to that future page in these notes is **not** evidence that the release exists. These notes can be bundled into CI-generated candidate archives before publication; **their presence does not by itself prove a release has been published**. The latest published prerelease remains [v1.0.0-rc.1](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) (November 20, 2026, UTC). The v0.5.5-beta.1 build is the last independently hardware-tested Windows rollback baseline.

**SmartThings channel:** [ARoedl SmartThings Edge Drivers](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20). Same channel and `computer-host-lan` driver/package identity; this candidate does not automatically upload or assign the Edge driver. Do **not** delete, reset or re-pair existing computer devices.

| Component | rc.2 candidate |
| --- | --- |
| Integration / release asset version | **1.0.0-rc.2** |
| Linux host agent | **0.4.6-rc.2** |
| Windows host agent | **0.2.7-rc.2** |
| SmartThings Edge driver | **0.4.6-rc.2** |
| Local protocol | **computer-host-agent v2 (unchanged)** |

## What changed since published v1.0.0-rc.1

**HTTP reliability — PR #56 (#30, #31):** Fix the LuaSocket override that inadvertently left Edge HTTP requests with a 60-second timeout instead of the configured four seconds. Enforce a cumulative five-second HTTP header deadline on Linux even when a slow client drips bytes without completing a line. Keep the 12 KiB header limit, concurrent-handler limit, API endpoints and protocol unchanged. A separate per-source connection cap was intentionally deferred pending LAN/NAT compatibility review; the deadline fix is not a full denial-of-service guarantee.

**Power acknowledgements — PR #57 (#33, #44):** On Windows, synchronous native shutdown/reboot request acceptance now precedes HTTP 202; an already-in-progress shutdown returns 409 and an immediate native failure returns 503. Suspend still acknowledges a queued delayed attempt, not completed sleep. On Linux, the privileged helper resolves and validates `systemctl` from fixed paths; shutdown/reboot acknowledge a **delayed attempt** before invoking `systemctl --no-block` after a one-second grace period, while suspend reports immediate execution errors. A 202 **never proves a completed power transition**; delayed shutdown failures cannot always be returned to the hub.

**Windows state security — PR #58 (#32):** Detect and reject untrusted pre-existing ProgramData ownership, permissive ACLs and reparse-point redirects before accepting retained credentials. New persistent-state folders are created with a protected ACL atomically; the state directory, token and agent-created files have path-specific ownership rules. This prevents the previously identified first-install key-planting route. Existing valid installation UUIDs, keys and configuration are **preserved** on ordinary upgrades and retained-state reinstalls; the installer never silently rotates them. A refusal needs administrator review, not deletion of a legitimate installation.

**Discovery, Wake and diagnostics — PR #59 (#34, #37, #46, #47):** Retry an unconfirmed SmartThings device-creation request after two minutes without duplicating normal pending requests. A failed Wake restores the last known On/Off state rather than inventing Off. Windows Setup now displays a Private-only firewall warning and the PowerShell installer warns if an active interface is Public; neither changes the Windows network profile or opens inbound access on Public. Linux's redacted `beta-report.sh` accepts `--port PORT` and reports stable/beta/RC versions without revealing credentials or raw host metadata.

**Publication and guidance — PR #60 (#52, #53, #54):** Correct the record of rc.1 publication, separate the published rc.1 binaries from newer `main` security guarantees, and ensure ZIP-packaged release notes match their source verbatim. The rc.1 release and its assets were **not** replaced.

## Installation and upgrade

**No rc.2 installer or source archive is publicly downloadable until the new tag and release assets have been explicitly approved and published.** CI build artifacts are only test candidates, not signed or permanent distribution files. Once published, obtain the version-matched **unsigned** Windows x64 Setup.exe or Linux source ZIP and `SHA256SUMS.txt` from the rc.2 release page. Verify the checksums; checksums hosted alongside mutable release assets do not independently authenticate their publisher. The ZIP/PowerShell Windows route remains a fallback.

For Windows installation and upgrade instructions see [quick start](QUICK-START.md) and [installation guide](../../INSTALLATION.md). Keep the host on a trusted private LAN; use only the selected hub IP address in the Windows Private firewall allow-list unless you deliberately choose the Private LocalSubnet fallback. A **Public** or **DomainAuthenticated** Windows profile is not covered by the Private-only firewall rule. Setup displays a static warning, not a live profile diagnosis.

**Do not uninstall first:** in-place upgrades must retain the existing SmartThings device, persistent installation UUID, `control-token`, custom listener port/settings, power opt-in choice and any rollback snapshot. New installations stay **monitoring-only by default**. Host-side power permission and the matching SmartThings `controlKey` and `allowPowerCommands` preference must be configured separately for any deliberate power testing. Back up and save work before invoking shutdown, reboot or suspend.

## Physical acceptance required before stable release

CI builds and automated Windows Server tests cannot establish real Windows 11 wizard rendering, administrator ACL behavior on every edition, hub mDNS discovery, WOL from every sleep/off state, or reliable shutdown acknowledgements under a real systemd stop-job. The rc.2 acceptance checklist tracks:

- Real Windows 11 **fresh install and in-place upgrade from the currently installed beta/rc.1**, preserving identity, key, port/config, firewall and existing SmartThings device.
- Installer Welcome/hub page and key-copy on the volunteer's actual screen; unexpected ProgramData owner/ACL rejection; optional Public-network warning and Private-profile connectivity.
- Real SmartThings hub discovery, an unconfirmed-create retry (when safely reproducible), service stop/restart, polling and metrics continuity, and failed Wake behavior.
- Real Linux Gentoo reference-host upgrade and optional safe shutdown/reboot/suspend/WOL cycles, with the returned HTTP status and SmartThings state recorded separately.
- Multi-day soak with no duplicate devices, permanent Offline states or unexpected credential changes.

These are **uncompleted acceptance gates**, not claims of tested hardware. The Linux per-source HTTP connection cap ([#31](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/31)), Linux helper hardware confirmation ([#44](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/44)) and Windows installer hardware confirmation ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)) remain tracked separately.

**A merged PR, generated ZIP, checksum file or these notes do not themselves publish a release, assign the Edge driver to a hub, or validate hardware.** Each is a separate explicit step.
