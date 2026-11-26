# Windows physical hardware test matrix (partially validated by volunteer)

**Verified v0.5.5 Windows 11 Pro volunteer (2026-11-20):** GUI in-place upgrade, preserved SmartThings device/settings, accurate CPU/RAM/disk telemetry, service stop/restart with Off/Unreachable → On/Running, Wake/Restart/Sleep controls, working WOL, and Windows agent 0.2.4-beta.1. The new v0.5.6 changes and other hardware/firmware/network combinations remain unverified.

For each tester record Windows version/build, OS powercfg states, wired NIC
model/driver, physical/virtual PC, and whether NIC is connected to hub LAN.
Do not collect personally identifying data or control keys.

1. Monitoring-only installation; service starts before logon; HTTP info/health/metrics.
2. mDNS discovered from a SmartThings hub; generic Windows profile rendered.
3. Agent service stop/start transitions: unreachable -> running, no duplicate device.
4. Power explicitly enabled; wrong key rejected; valid reboot command restarts;
   boot ID changes; system metrics recover; no data loss.
5. Traditional S3 sleep if supported, `Suspend` -> WOL wake; boot ID unchanged.
6. Modern Standby / S0 Low Power Idle: document network and wake behavior.
7. Hibernate S4 explicitly: record whether WOL wakes (not guaranteed).
8. Shut down from app with unsaved documents: should show 15-second countdown,
   NOT forcibly close user apps; shutdown can be cancelled by Windows.
9. WOL after explicit shutdown S5/Fast Startup: record success or failure,
   never represent as universally supported.
10. Verify next boot `Wake-on: g` analogy via Windows adapter driver settings,
    `powercfg /a`, `Get-NetAdapterPowerManagement` and physical wake.
11. Repeat after IP change, hub restart, service upgrade, and system boot.

Always test sleep and reboot before shutdown, with physical recovery available.
Run read-only `scripts/Get-WolDiagnostics.ps1` and redact network details before
sharing feedback. Do not publish private keys.

12. DNS-SD recovery (#132/#124): after a DHCP address change or resume, restore
    LAN connectivity and verify hub rediscovery of the same device within 180 s,
    without agent restart or re-pairing. Repeat after adapter reconnect; record
    elapsed time and redacted registration status. Failure blocks rc.3 pending
    bounded, debounced network-change re-registration. CI is not hardware evidence.
