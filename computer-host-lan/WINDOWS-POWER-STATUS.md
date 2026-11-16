# Windows power-management status — 0.2.0-alpha.1

Implemented in C# source, **not Windows-build-validated or hardware tested**:

- HMAC-SHA256 (same Linux v2 wire format) and bounded 30-second single-use nonces.
- LocalService privilege enablement at request time; InitiateSystemShutdownEx
  (reboot/shutdown, 15-second countdown, no forced applications) and SetSuspendState
  (sleep, wake events kept enabled); operation queued after HTTP 202 response.
- Candidate wired NIC MAC/subnet broadcast in `/v2/info`; hub sends WOL.
- Power opt-in at installer (`-EnablePower`) and SmartThings preference; disabled
  by default; token preserved across upgrades; protected ProgramData state.
- Windows profile now includes Wake/Reboot/Suspend controls.

**Not yet done:** real C# compilation, Windows Service execution, native DNS-SD
interoperability, ACPI/Modern Standby tests, WOL after S3/S4/S5, signed installer.

The included GitHub Actions workflow will compile and run non-destructive smoke
checks when pushed to a source branch. It never sends a valid power request.

Deploy via scripts/Stage-New-Project.sh from an authenticated Git checkout.
