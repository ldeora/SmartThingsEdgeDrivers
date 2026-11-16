# Computer Host Agent protocol v2 (development draft)

**Applies to:** Linux agent and generic SmartThings Edge Driver v0.4.0-dev.1.
**Not backward compatible with protocol v1.** All endpoints are under `/v2/`.
The v0.3.1 contract is archived in `docs/history/v0.3.1-beta.1/PROTOCOL.md`.

## Discovery and identity

* DNS-SD service: `_computerhost._tcp.local` (Avahi on Linux).
* Default TCP port: 8765 (plain HTTP over a trusted LAN only).
* Every successful JSON response MUST contain
  `protocol: "computer-host-agent"`, `api_version: 2`,
  `platform: "linux" | "windows"` and stable installation UUID `id`.
  Error objects may omit these envelope fields.
* The Edge Driver validates protocol, version, platform and UUID and checks
  UUID again before saving metadata, reporting telemetry or sending power.
* `platform` is the operating-system family, not the firmware power state.
  The current implementation advertises only `linux`; the Windows prototype
  must implement the same contract without using Linux system APIs.
* Network candidates must be verified by querying `/v2/info`; unsolicited
  mDNS advertisements alone are not sufficient to associate a device.
* Identifier prefix: `computer-host:<lowercase UUID>`; previous identities
  are not migrated in this developer release.

## HTTP routes

| Method | Path | Authentication | Expected outcome |
| --- | --- | --- | --- |
| GET | `/v2/info` | None | Identity, platform, capabilities, WOL metadata, power actions |
| GET | `/v2/health` | None | Matching UUID, `status=running`, boot ID, uptime |
| GET | `/v2/metrics` | None | CPU/memory/disk/temp/uptime and optional load metrics |
| GET | `/v2/challenge` | None | 48 hex nonce; only when power enabled |
| POST | `/v2/power/shutdown` | HMAC | 202 acceptance or error |
| POST | `/v2/power/reboot` | HMAC | 202 acceptance or error |
| POST | `/v2/power/suspend` | HMAC | 202 acceptance or error |

Successful power command acceptance is **not** proof of the final host state.
The Edge Driver retains the original state inference model.

### `/v2/info` example (Linux)

```json
{
  "protocol": "computer-host-agent", "api_version": 2,
  "agent_version": "0.4.0-dev.1", "platform": "linux",
  "id": "0b5553a0-9b6b-4ef7-83d8-fbe3c913719d",
  "hostname": "workstation", "os": "Linux",
  "features": ["health", "metrics", "wol-metadata", "power-control"],
  "power_actions": ["reboot", "shutdown", "suspend"],
  "wol_mac": "02:11:22:33:44:55",
  "wol_broadcast": "192.0.2.255",
  "wol_interface": "eth0"
}
```

### `/v2/health` example

```json
{
  "protocol": "computer-host-agent", "api_version": 2,
  "platform": "linux", "id": "0b5553a0-9b6b-4ef7-83d8-fbe3c913719d",
  "status": "running", "boot_id": "46e33e61-d83e-44ce-ae39-d00c1dfeefcb",
  "uptime_seconds": 85946.1
}
```

### `/v2/metrics` field names

| Field | Meaning | Linux | Planned Windows |
|---|---|---|---|
| `cpu_usage_percent` | Total CPU utilization, percent | Yes | Yes |
| `memory_usage_percent` | Memory utilization, percent | Yes | Yes |
| `memory_total_bytes` | Installed RAM | Yes | Yes |
| `disk_root_usage_percent` | System/root filesystem utilization | Yes | Define system-drive mapping |
| `uptime_seconds` | System/kernel uptime | Yes | Test Fast Startup semantics |
| `boot_id` | Identifies a real boot session | Yes | Requires Windows boot-session implementation |
| `cpu_temperature_c` | Sensor temperature or `null` | If available | Optional; no universal API |
| `cpu_temperature_label` | Source description | If available | Optional |
| `load_1m`, `load_5m`, `load_15m` | Linux load averages | Yes | Omit; not directly comparable |

Missing measurements may be JSON `null`. The Edge Driver skips unavailable
numeric data; it does not substitute zero. The first CPU utilization reading
may be null because it requires sampling a delta.

## Authentication

* `GET /v2/challenge` returns a fresh lower-case 48-hex-character nonce
  valid for 30 seconds. Requests may be rate-limited (HTTP 429 / Retry-After).
* The key is 32 random bytes represented as 64 hex characters; the SmartThings
  device preference must contain the matching secret. Do not log or expose it.
* Signed requests have `Content-Length: 0` with **no request body**.
* Signature: `HMAC-SHA256(bytes.fromhex(key), ASCII("POST\n" + path + "\n" + nonce + "\n"))`.
* Header names: `X-ComputerHost-Nonce` and `X-ComputerHost-Signature`
  (lowercase hex signature). Nonces are one-time-use. No silent retry of
  accepted signed requests.
* POST response on acceptance is HTTP 202 including `accepted:true`, `action`,
  UUID and protocol envelope. Unauthorized=401, disabled=403,
  helper unavailable=503, unacceptable request=400/404.

Transport is plain HTTP: HMAC does **not** provide monitoring confidentiality,
end-to-end response integrity, or identity authentication for read-only calls.
Restrict inbound connections to a trusted LAN/hub. TLS/mutual authentication
can be considered in a later protocol revision after the hub's capabilities
and provisioning UX are investigated.

## Device profiles and behavior

* `computer-host-linux`: five generic monitoring capabilities plus `linuxLoad`.
* `computer-host-windows`: generic capabilities only; no Linux load averages.
* `computer-host`: standard-capability fallback.
* Switch OFF currently means authenticated **shutdown**. This is appropriate
  for verified Linux behavior. The Windows agent must not claim wake-from-
  shutdown works universally; configurable sleep/shutdown behavior is a
  future Windows-specific implementation task.

The monitoring intervals, power-state inference, WOL metadata persistence,
identity checks, failure handling, and security limits are inherited from
Linux v0.3.1-beta.1. Hardware-level equivalence still requires validation.

## Windows power-control extension (v2, unchanged wire contract)

The Windows agent may advertise `power_actions` of `reboot`, `shutdown`, and
`suspend` only when the Windows service is explicitly installed with
`-EnablePower`. The same Linux-compatible `/v2/challenge` and authenticated
`POST /v2/power/<action>` endpoints are used; HMAC-SHA256 covers
`POST\n/v2/power/<action>\n<nonce>\n`, where nonce is 24 random bytes
(48 lowercase hex characters). Keys are 32 random bytes (64 hex). Nonces
expire after 30 seconds and are consumed once. HTTP 202 acknowledges acceptance
of a command, not actual shutdown/suspend completion.

The Windows agent advertises a best-effort wired Ethernet MAC and subnet
broadcast if detected. This is **not** evidence that Wake-on-LAN works on any
particular device or power state. WOL must be tested on real hardware.
Windows power and WOL are disabled by default on fresh installations.
