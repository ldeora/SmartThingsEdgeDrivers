# Protocol v1 — v0.3.0 security amendment

Agent v0.3.0 preserves the same endpoints, payloads, API version and signed
request construction as v0.2.2. A new response code **HTTP 429** can appear
for excessive `/v1/challenge` requests; it carries `Retry-After: 30`.
The client may retry after a delay. No accepted signed power command is
silently retried. HTTP keepalive is disabled; partial requests time out.
Refer to [SECURITY-HARDENING.md](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/97b078727180096631ca52b7892f168086d0490b/computer-host-lan/SECURITY-HARDENING.md) for resource limits and
trust boundaries.

---

# Linux Host LAN protocol v1 — agent v0.2.2 / Edge v0.2.9

Service discovery: DNS-SD `_linuxhost._tcp.local`, advertised via Avahi.
TCP port: 8765 by default. Content type: `application/json`, UTF-8.
Every returned object includes `protocol: "linux-host-agent"`, `api_version: 1`
and a stable installation UUID `id` (except error objects). The SmartThings
Edge driver checks this UUID to prevent associating another computer with the
same reassigned IP address.

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| GET | `/v1/info` | None | Identity, features, WOL MAC/broadcast, supported power actions |
| GET | `/v1/health` | None | `running`, boot ID, uptime in seconds |
| GET | `/v1/metrics` | None | CPU/memory/disk/load/temperature/uptime |
| GET | `/v1/challenge` | None | 48-hex-character single-use nonce, valid 30 seconds |
| POST | `/v1/power/shutdown` | HMAC | Graceful systemd poweroff |
| POST | `/v1/power/reboot` | HMAC | systemd reboot |
| POST | `/v1/power/suspend` | HMAC | systemd suspend |

Power requests have no body (`Content-Length: 0`). Signature is
HMAC-SHA256 over ASCII bytes:

```
POST\n/v1/power/<action>\n<nonce>\n
```

Headers: `X-LinuxHost-Nonce: <nonce>` and
`X-LinuxHost-Signature: <lowercase 64-hex HMAC>`.
The secret is 32 random bytes encoded as 64 hexadecimal characters in the
agent's persistent state directory. The agent consumes a nonce before checking
its signature, preventing replay. Successful requests return HTTP 202 with
`accepted:true`, the action and the installation ID; they do not prove that
systemd actually powered off or suspended the host. Unauthorized requests
return 401; helper unavailable returns 503; disabled control returns 403.

### Example `/v1/info`

```json
{
  "protocol": "linux-host-agent", "api_version": 1,
  "agent_version": "0.2.2", "id": "0b5553a0-9b6b-4ef7-83d8-fbe3c913719d",
  "hostname": "workstation", "os": "Linux",
  "features": ["health", "metrics", "wol-metadata", "power-control"],
  "power_actions": ["reboot", "shutdown", "suspend"],
  "wol_mac": "00:11:22:33:44:55", "wol_broadcast": "192.168.50.255",
  "wol_interface": "enp3s0"
}
```

### Example `/v1/metrics`

```json
{
  "protocol": "linux-host-agent", "api_version": 1,
  "id": "0b5553a0-9b6b-4ef7-83d8-fbe3c913719d",
  "cpu_usage_percent": 17.4,
  "memory_usage_percent": 32.1,
  "memory_total_bytes": 34359738368,
  "cpu_temperature_c": 48.5,
  "cpu_temperature_label": "k10temp Tctl",
  "disk_root_usage_percent": 63.0,
  "load_1m": 0.55, "load_5m": 0.7, "load_15m": 0.81,
  "uptime_seconds": 85946.1,
  "boot_id": "46e33e61-d83e-44ce-ae39-d00c1dfeefcb"
}
```

A metric can be `null` if unavailable. First `cpu_usage_percent` request
may be `null` because delta-based CPU usage requires two snapshots. The
server deliberately does not report potentially misleading GPU/NVMe thermal
readings as CPU temperatures. `disk_root_usage_percent` is for the root
filesystem where `/` resides; it is not total physical disk usage.

## Agent 0.2.2 WOL metadata selection

`GET /v1/info` retains the same protocol (`api_version: 1`) and field names. In automatic mode, the WOL interface is reselected on every request instead of being determined only at process startup. Until an IPv4 NIC becomes available, `wol_*` fields can legitimately be `null`; this condition should clear on later requests without restarting the daemon. An explicit `--wol-interface` or `LINUX_HOST_WOL_INTERFACE` pins an interface. The Edge Driver v0.2.5 stores validated metadata and does not accept metadata from a different installation UUID.


## Edge Driver telemetry presentation (v0.2.7)

The Edge Driver maps the existing metrics response to the advanced SmartThings
profile as follows:

| API field | Custom capability attribute | Presentation |
|---|---|---|
| `cpu_usage_percent` | `linuxCpuUsage.cpuUsage` | CPU utilization (%) |
| `memory_usage_percent` | `linuxMemoryUsage.memoryUsage` | Memory utilization (%) |
| `memory_total_bytes` | `linuxMemoryUsage.memoryTotalGiB` | Installed RAM (GiB) |
| `disk_root_usage_percent` | `linuxDiskUsage.diskUsage` | Root filesystem usage (%) |
| `uptime_seconds` | `linuxUptime.uptimeMinutes` | Numeric uptime in minutes |
| `uptime_seconds` | `linuxUptime.uptimeText` | `Xd Yh` or `Xm` |
| `load_1m` | `linuxLoad.loadOne` | 1-minute load average |
| `load_5m` | `linuxLoad.loadFive` | 5-minute load average |
| `load_15m` | `linuxLoad.loadFifteen` | 15-minute load average |

The host-state capability is emitted by the Edge Driver's existing availability
and power-action state machine. The metrics are latest-state indicators, not
long-term performance history. High-frequency custom metric events use
`visibility.displayed=false` to keep the mobile-app event history concise.

## v0.2.9 state semantics

See `STATE-MODEL.md`. The `linuxHostStatus.status` schema has NOT changed;
`running` is a confirmed agent response, while `stopped` and `suspended`
are conclusions drawn from an acknowledged power command followed by repeated
silent failures. A timeout without such a command reports `unreachable` even if
the main switch is configured to infer OFF. An `unreachable` state does not
prove power loss; `unknown` covers identity/protocol failures.
