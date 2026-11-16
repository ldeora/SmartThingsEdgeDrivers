> **Historical Linux-only v0.3.1 source document.** It describes the
> pre-refactor release and must not be used as evidence of hardware
> validation for v0.4.0-dev.1. For the current architecture read
> `README.md`, `PROTOCOL.md`, `INSTALLATION.md` and
> `docs/development/LINUX-PARITY-ACCEPTANCE.md`.

# Security review for prospective public release (2026-11-15)

**Not an independent security audit. No Internet exposure is safe.**

## Current safeguards verified by source inspection

- Non-root HTTP agent; dedicated `linuxhost` account and isolated persistent
  state files (`0600`); systemd sandbox restrictions.
- Root-only helper reached over Unix socket with `SO_PEERCRED` UID check;
  allowed actions restricted to shutdown/reboot/suspend, no arbitrary shell.
- HMAC-SHA256 with path/nonce signing and single-use 30-second challenge;
  secret is not sent in plain HTTP requests.
- Power control requires explicit opt-in both on Linux host and SmartThings.
- Driver checks persistent host UUID when refreshing WOL metadata.

## Release blockers / design risks

**High priority**

1. **Unencrypted LAN traffic:** HMAC authenticates requests but does not
   encrypt telemetry, host identifiers or response bodies. A network attacker
   can observe, block, or tamper with unauthenticated GET responses. Default
   listener is `0.0.0.0:8765`, so the local firewall is essential.
2. **Secret stored in SmartThings device preference:** treat the HMAC key as
   credential material. Preference visibility/account sharing and device
   migration/rotation need investigation. Do not publish it in logs or support
   tickets. Consider provisioning/credential design before public GA.
3. **Python `http.server`** is explicitly not recommended by Python for
   production deployments. The current `ThreadingHTTPServer` has no explicit
   bounded thread-pool, per-client request limits or socket timeouts. Harden
   the HTTP listener or replace it with a vetted service framework, then
   regression-test all signed power actions.
4. **Challenge allocation:** current nonce storage is capped at 128 but
   resets the entire cache when full. A hostile LAN client could deny valid
   requests by repeatedly requesting challenges. Replace this with a proper
   bounded/expiry data structure plus rate limiting.
5. **Power helper acknowledgement:** the helper sends `OK` before invoking
   systemctl. Reported acceptance is not execution confirmation; failure
   needs to be logged and reflected in diagnostics. Remote inference must
   remain explicit.

**Compatibility/security validation**

6. Validate SELinux enforcing (Fedora/RHEL/SUSE 16), AppArmor where used,
   file labels and access to `/proc`, `/sys`, `/var/lib`, Unix socket.
7. Validate reproducible source package permissions, hash/signature
   verification, installer rollback, symlink handling and path ownership.
8. Ensure HTTP endpoints disclose only intended host information and support
   redacted diagnostic export. Test malformed headers, oversized requests,
   replay, response tampering and hostile high-concurrency connections.
9. Require a trusted LAN/firewall that restricts TCP/8765 to the hub; do NOT
   configure a port-forward or publish a token or logs containing it.

## Beta gate

Before unrestricted public beta: address items 1–5 with tested mitigations
or documented, explicitly accepted limitations; run targeted negative tests.
The known-working power logic remains unchanged in v0.2.11; no claim of an
external penetration test is made.

Sources:
- https://docs.python.org/3/library/http.server.html
- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
