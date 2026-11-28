# Computer Host Agent protocol v2

Current wire contract for Computer Host LAN. Integration and agent versions are independent of protocol version; see [product overview](../../README.md). Protocol v1 is incompatible. All routes are under `/v2/`. Preserve installation identity and existing field semantics; additive optional fields may be introduced without changing v2.

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
  Both `linux` and `windows` are implemented and must follow the same wire
  contract; Windows-specific metrics and power API calls remain platform-specific.
* Network candidates must be verified by querying `/v2/info`; unsolicited
  mDNS advertisements alone are not sufficient to associate a device.
* Identifier prefix: `computer-host:<lowercase UUID>`; normal upgrades preserve the same identity
  and SmartThings device; protocol-v1 identities remain separate.

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
See [driver state model](architecture.md#state-and-power-transitions).

### `/v2/info` example (Linux, illustrative version)

```json
{
  "protocol": "computer-host-agent", "api_version": 2,
  "agent_version": "0.4.7-rc.3", "platform": "linux",
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

| Field | Meaning | Linux | Windows |
|---|---|---|---|
| `cpu_usage_percent` | Total CPU utilization, percent | Yes | Yes |
| `memory_usage_percent` | Memory utilization, percent | Yes | Yes |
| `memory_total_bytes` | Installed RAM | Yes | Yes |
| `memory_used_bytes` | Physical RAM used; total minus available (optional) | Yes | Yes |
| `memory_available_bytes` | Physical RAM available to programs (optional) | MemAvailable | AvailPhys |
| `disk_root_usage_percent` | System/root filesystem utilization | Yes | System drive |
| `disk_root_total_bytes` | Total capacity of the same root/system filesystem in bytes (optional; null if unavailable) | Yes | System drive |
| `disk_root_used_bytes` | Allocated blocks/space on root/system volume (optional) | f_blocks minus f_bfree | TotalSize minus TotalFreeSpace |
| `disk_root_available_bytes` | Available bytes on same filesystem/volume (optional) | f_bavail | AvailableFreeSpace |
| `uptime_seconds` | System/kernel uptime | Yes | Kernel uptime; Fast Startup may retain it |
| `boot_id` | Identifies a real boot session | Yes | Protected heuristic boot-session ID |
| `cpu_temperature_c` | Sensor temperature or `null` | If available | Not reported |
| `cpu_temperature_label` | Source description | If available | Not reported |
| `load_1m`, `load_5m`, `load_15m` | Linux load averages | Yes | Omit; not directly comparable |

Missing measurements may be JSON `null`. The Edge Driver skips unavailable
numeric data; it does not substitute zero. The first CPU utilization reading
may be null because it requires sampling a delta.

`disk_root_total_bytes` is an **additive, optional** v2 metrics field. Old
agents may omit it; old drivers ignore it. It is measured for the same root
filesystem (Linux `/`) or system volume (Windows) as
`disk_root_usage_percent`. Linux uses `statvfs` filesystem capacity, not
sum of physical disks or a drive vendor's advertised capacity. The Edge
Driver converts bytes into GiB (2^30 bytes) for display. No device discovery,
identity, authentication or command semantics change.

### Optional used and available byte counts

The four additional v2 metrics `memory_used_bytes`,
`memory_available_bytes`, `disk_root_used_bytes` and
`disk_root_available_bytes` are **optional**. Older protocol-v2 agents
continue working without them. The Edge driver converts valid byte counts
into GiB rounded to one decimal; missing and invalid values are not invented.

For RAM, Linux `MemAvailable` and Windows `GlobalMemoryStatusEx.AvailPhys`
are used, with used = total − available. Linux `MemFree` is not equivalent
to available RAM because reclaimable page cache is excluded.

Filesystem used bytes are actual allocated blocks (`f_blocks - f_bfree` on
Linux and `TotalSize - TotalFreeSpace` on Windows), while available bytes
are those accessible to the process (`f_bavail` or
`AvailableFreeSpace`). Reserved blocks, btrfs accounting and quotas may
mean **Used + Available ≠ Total**. Existing disk percentage remains
`(Total - Available) / Total`, and may therefore differ from
`Used / Total`. Do not silently change its established automation semantics.

Existing custom capability attributes must retain their semantics. Account-level schemas, translations and presentations are independent of driver packaging; see [development and rollout](../development.md#capabilities-and-presentations).

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

## Validation and error handling

The driver checks the protocol envelope, platform and expected installation
UUID at info, health, metrics, challenge and power-response boundaries.
An mDNS advertisement or matching UUID is not cryptographic identity proof.
A POST is accepted only with valid authorization and a supported action;
HTTP 409 means another operation is pending or the OS reports a shutdown
already in progress, not successful acceptance. HTTP 503 covers immediate
helper/native failures. Do not retry an uncertain accepted request.

Linux limits HTTP headers to 12 KiB, with a five-second cumulative header
deadline; both agents limit active connections to twelve globally and four
per remote source. Challenge admission is bounded; Linux allows 20 challenges
per source per rolling minute with at most 128 pending nonces. The Edge
driver limits replies to 32 KiB and does not follow redirects. Its four-second
inactivity timeout is supplemented by an eight-second cooperative request
deadline (separate budgets for challenge and POST); fallback to inactivity
only is a compatibility limitation, not successful transport qualification.
See [security](../../SECURITY.md) for trust boundaries.

Windows and Linux use the same authentication construction and routes.
Power advertisement is opt-in and depends on host permissions and safe
credentials. WOL metadata is best effort; WOL magic packets are sent by
the hub, outside the HTTP protocol and without authentication. WOL does not
require authenticated shutdown/reboot/suspend to be enabled.

See [architecture](architecture.md) for discovery, state transitions and
platform-specific acceptance points, and [SmartThings settings](../smartthings.md)
for user-visible controls.

## Release consistency

Release engineering verifies the component-version constants against `release.json` and reads the running Windows agent's `/v2/info.agent_version` in native Windows CI. A reported runtime version mismatch is a release defect, even when protocol v2 is compatible. Existing beta devices retain their UUID and profile component IDs across version updates.
