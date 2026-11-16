# Computer Host LAN — Cross-platform SmartThings integration

**Development release v0.5.1-dev.1** (source only, 2026-11-16). Separate project
from `linux-host-lan/`, which remains untouched and available for rollback.

One SmartThings LAN Edge Driver, a Linux agent (Python/systemd/Avahi) and a
native Windows agent (C#/.NET 10/Windows Service/native DNS-SD), all using the
same protocol v2 and `_computerhost._tcp.local` discovery.

## Verified status

- **Linux v0.4.0-dev.1:** Tested on Gentoo `hydra` and a SmartThings hub for
  telemetry, mDNS discovery, agent interruption/recovery, reboot, suspend/WOL,
  and shutdown/WOL. Linux code and driver Lua code were not changed for this
  Windows power-management iteration.
- **Windows v0.2.0-alpha.1:** Source implementation of monitoring plus opt-in
  HMAC-authenticated reboot, shutdown, suspend and candidate WOL metadata.
  **Not compiled or executed on Windows yet; no hardware claims.**
- Power commands default OFF. Windows wake from S5/Fast Startup is unsupported
  by Microsoft even though some firmware may allow it.

Start with [Windows agent README](windows-agent/README.md), [protocol](PROTOCOL.md),
[testing](windows-agent/docs/HARDWARE-TEST-MATRIX.md) and [security](SECURITY.md).
The real GitHub Actions workflow belongs at repository root
`.github/workflows/computer-host-windows.yml`, not inside this subdirectory.

No installer runs as part of extraction. Do not deploy the unverified Windows
power agent on an unattended or nonrecoverable computer.
