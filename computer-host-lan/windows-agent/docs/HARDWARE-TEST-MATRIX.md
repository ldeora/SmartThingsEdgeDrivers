# Windows physical hardware test matrix (partially validated by volunteer)

# First Windows 11 volunteer: installation/basic SmartThings operation and the Suspend, Reboot and Shutdown (Off) commands were reported working in November 2026. This does not close the full matrix below; WOL was not yet tested, and metrics, service recovery and diverse Windows hardware still need explicit results.

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
