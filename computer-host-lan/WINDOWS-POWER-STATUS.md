# Windows power management — v0.2.0-alpha.1

**Implementation:** Opt-in HMAC-SHA256 challenge/response using shared protocol v2; reboot/shutdown via Windows `InitiateSystemShutdownEx` (15-second countdown, no forced application termination); suspend via `SetSuspendState(false,false,false)`. Wake packets originate from the **SmartThings hub**, using reported candidate wired NIC metadata or user overrides.

**Verified on Windows Server 2025 CI:** Self-contained build, negative/positive authentication and nonce-replay contract tests, service installation as `NT AUTHORITY\LocalService`, protected persistent identity/key directory, PowerShell 5.1 install, enabling/disabling *advertised* power actions. CI deliberately **never executes an authenticated power command**.

**Acknowledgement behavior:** Shutdown and reboot now call `InitiateSystemShutdownEx` before returning HTTP 202. Immediate native failures are surfaced: `ERROR_SHUTDOWN_IN_PROGRESS` becomes HTTP 409 and other failures become HTTP 503. The API is still called with forced application closure disabled; an unsaved application can keep the graceful shutdown pending until the console user responds. Suspend retains a three-second delayed background call so the 202 response can reach the hub first; that response confirms only that the service queued the attempt. No 202 confirms the eventual physical power-state transition.

**Not verified:** Real Windows 11 suspend/reboot/shutdown; whether `SeShutdownPrivilege` is effective under each user's policy; Modern Standby/S3/S4/S5 wake behavior; Windows Fast Startup; multi-NIC/Windows DNS-SD interoperability with SmartThings hardware. CI uses injected power-operation delegates and deliberately never executes an authenticated native power command.

**Tester sequence:** monitor first → reboot with physical recovery → suspend then WOL → full shutdown then WOL last. Install without `-EnablePower` to disable power again; treat the 64-hex control key as confidential. Do not use a production or remotely unrecoverable PC.
