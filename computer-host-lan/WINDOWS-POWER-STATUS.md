# Windows power management — v0.2.0-alpha.1

**Implementation:** Opt-in HMAC-SHA256 challenge/response using shared protocol v2; reboot/shutdown via Windows `InitiateSystemShutdownEx` (15-second countdown, no forced application termination); suspend via `SetSuspendState(false,false,false)`. Wake packets originate from the **SmartThings hub**, using reported candidate wired NIC metadata or user overrides.

**Verified on Windows Server 2025 CI:** Self-contained build, negative/positive authentication and nonce-replay contract tests, service installation as `NT AUTHORITY\LocalService`, protected persistent identity/key directory, PowerShell 5.1 install, enabling/disabling *advertised* power actions. CI deliberately **never executes an authenticated power command**.

**Not verified:** Real Windows 11 suspend/reboot/shutdown; whether `SeShutdownPrivilege` is effective under each user's policy; Modern Standby/S3/S4/S5 wake behavior; Windows Fast Startup; multi-NIC/Windows DNS-SD interoperability with SmartThings hardware. A 202 response means the request was queued, not physically completed.

**Tester sequence:** monitor first → reboot with physical recovery → suspend then WOL → full shutdown then WOL last. Install without `-EnablePower` to disable power again; treat the 64-hex control key as confidential. Do not use a production or remotely unrecoverable PC.
