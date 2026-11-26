# Computer Host LAN — release history and earlier test evidence

Historical context only. Earlier test results do not qualify rc.3. See [current readiness](../release/RC3-READINESS.md).

## Published rc.2 versus older rc.1

The [older rc.1 release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.1) was built from tag `5466ad0`. Published rc.2 adds PRs #56–#60: HTTP timeouts/header deadlines, power acknowledgments, hardened Windows ProgramData state, discovery/Wake recovery and publication guidance. See the [rc.2 notes](../release/RELEASE-NOTES-v1.0.0-rc.2.md) and [installation guide](../../INSTALLATION.md#known-differences-between-rc1-and-rc2). Passing CI is not physical Windows 11 acceptance.

**Historical rc.1 security caution:** rc.1 lacks PR #58's retained-state and credential protections ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)). Do not enable rc.1 authenticated power on a shared PC with untrusted local users; checking ProgramData once does not eliminate its fresh-install race. Prefer published rc.2 and preserve existing UUIDs/keys. See [rc.1 security limitations](../../SECURITY.md#known-issues-in-the-published-rc1).

Computer Host LAN is a **separate** project from [Linux Host LAN](../../../linux-host-lan/). It uses the `_computerhost._tcp` discovery service and `/v2` HTTP API. **Do not pair a protocol-v1 Linux Host LAN agent with this driver.**

## What has actually been tested?

| Target | Evidence |
| --- | --- |
| Linux / Gentoo on `hydra` | Real hub: discovery, monitoring, recovery, reboot, suspend/WOL and shutdown/WOL; on 2026-11-18 verified the RAM/filesystem values; the publisher reports an rc.2 Linux upgrade working as expected (2026-11-21), without individually documented rc.2 power/soak results |
| Linux / Debian 12–13, Ubuntu 24.04–26.04, Fedora 43–44 | Source/container tests passed in CI; no physical power/state certification |
| Windows x64 | .NET 10 build, protocol/security tests, HTTP smoke, installation as `NT AUTHORITY\LocalService` and opt-in/opt-out tested on Windows Server 2025 runner ([CI](https://github.com/ldeora/SmartThingsEdgeDrivers/actions/runs/43827358333)) |
| Windows ARM64 | Cross-publish passed; not executed on ARM64 hardware |
| Windows 11 with a SmartThings hub | Public-beta tester reports successful **graphical Setup installation and upgrade** on Windows 11 Pro; screenshot shows CPU, memory and system-drive telemetry correctly displayed. A v0.5.5 Windows 11 tester also confirmed correct service recovery, Wake/Restart/Sleep controls and working Wake-on-LAN. The rc.2 Windows-specific changes still require physical Windows 11 acceptance. |

Windows system metrics include CPU, RAM, system-drive usage and uptime. Both agents now report **Usage %, Total GiB, Used GiB, Available GiB** for RAM and their root/system filesystem. The new byte fields are optional protocol-v2 additions; old agents remain supported. On Linux, reserved filesystem blocks mean Used + Available may differ from Total. CPU temperature and Linux load averages are not invented on Windows. Shutdown/reboot/suspend are opt-in, best-effort and HMAC-authenticated. WOL is sent by the hub and depends on the NIC, firmware, network topology and Windows power state.

See [rc.3 readiness and physical acceptance](../release/RC3-READINESS.md),
[stable release gates](../release/V1-RELEASE-GATES.md) and
[older rc.2 acceptance](../release/RC-ACCEPTANCE.md). Published rc.2 source
commit: `72e4a99c4b2e8f958ce771152826319318d0d537`. Earlier hardware results
are not rc.3 acceptance. Keep the existing Computer Host LAN driver/channel
and devices. The v0.5.5-beta.1 release remains an earlier independently
Windows 11 hardware-tested fallback; it is not evidence for rc.3.
