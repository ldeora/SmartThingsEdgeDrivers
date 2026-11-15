# Security design and release blockers — v0.3.0 preview

**Not an independent security audit. Not safe on an untrusted LAN or the
public Internet.** It is an incremental reduction in attack surface.

## Implemented in v0.3.0

- Default agent remains **unprivileged** (`linuxhost`) with systemd
  `ProtectSystem=strict`, `ProtectHome`, no-new-privileges and restricted
  address families. Added `MemoryMax`, `TasksMax`, file-descriptor limits,
  `RestrictSUIDSGID`, `LockPersonality`, `ProtectHostname` and syscall
  architecture restrictions. Check compatibility with each target OS.
- Bounded HTTP server allows at most **12 active client connections** with
  **4-second socket-inactivity timeouts**, a **5-second cumulative HTTP header deadline**, a **12 KiB header budget**, and listen backlog 16.
  Connections exceeding the cap are closed (caller should retry).
- Challenge issuance is limited to **20 requests per minute per source IP**
  and **120 per minute overall**, with a bounded client map and 128 live
  challenge slots. Saturation returns HTTP 429 with `Retry-After: 30`.
- Live 30-second nonces are **never evicted** to make room for new challenges.
  An invalid signature does not consume a legitimate nonce; a successful
  signature still consumes it exactly once, preserving replay protection.
- No HTTP request path or arbitrary header text is logged by the agent;
  control secrets/HMAC signatures are never intentionally logged.
- Root-side helper accepts only `shutdown`, `reboot`, `suspend`, over a Unix
  socket restricted to the `linuxhost` UID via `SO_PEERCRED`. Added a 3-second
  read timeout and minimal non-secret error logging.
- **Power control is opt-in**. The installer preserves opt-in on upgrade,
  or explicitly disables it using `--disable-power`.
- Installation writes app-owned files atomically; a root-only snapshot enables
  rollback. Persisted UUID/key and WOL settings are never overwritten.
- Firewall rules, sysctls, distribution Python symlinks, and SELinux policy are
  never modified by the installer.

## Protocol compatibility

The API remains `api_version=1`, with the same HMAC message
`POST\\n<path>\\n<nonce>\\n`; no Edge driver changes are needed. The agent
version changes to 0.3.0. New responses (429 for throttling) occur only when
limits are reached.

## Important limitations still open

1. **Cleartext HTTP** on TCP 8765. HMAC protects authorization but not
   metadata confidentiality, response integrity, or an active LAN MITM.
   Firewalls should allow traffic *only from the SmartThings hub* when possible.
   No port forwarding and no untrusted Wi-Fi.
2. **SmartThings preference is credential storage.** The control key is stored
   as a device setting, which may be accessible to users with sufficient
   account/administration privileges. Review an alternative provisioning
   protocol and documented rotation before stable release.
3. **Python `http.server` still carries production limitations.** The added
   resource bounds do not amount to comprehensive HTTP parser hardening.
   Under hostile LAN traffic it can still be denied service. An independent
   security review or vetted network-service replacement is a release gate.
4. **Root helper acknowledges before the power command completes.** The
   acknowledgement means accepted, not executed/completed. State transitions
   remain inference-based until the agent or system stops responding.
5. **Firewall and LSM policies** vary by distro, image and network manager.
   SELinux (enforcing) and AppArmor scenarios require VM/hardware testing.
6. **Remote Wake-on-LAN** is inherently unauthenticated. Access to the LAN
   may be sufficient to wake the machine, whether SmartThings is involved or not.

## Operational handling

- Never post the key at `/var/lib/linux-host-agent/control-token`, even in
  private support discussions; never attach raw signed requests.
- A compromised key requires coordinated rotation on the Linux host and
  SmartThings device preference. Do not erase `installation-id` when rotating.
- The trusted LAN must enforce firewall policy outside this installer. Where
  possible allow only the hub's IP to access TCP/8765 and enable multicast
  UDP/5353 only as required for local discovery.
- Test under firewall-denied, agent-stopped, reboot, suspend and shutdown
  conditions; the main Switch is an inferred logical state, **not** an
  electrical power meter.

References:
- https://docs.python.org/3/library/http.server.html
- https://docs.python.org/3/library/socketserver.html
- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
