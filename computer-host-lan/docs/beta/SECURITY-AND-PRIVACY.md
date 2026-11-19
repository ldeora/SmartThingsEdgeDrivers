# Computer Host LAN — public beta security and privacy

**Trusted private LAN only.** The host agent's monitoring HTTP API (`/v2/info`, `/v2/health`, `/v2/metrics`) is not TLS encrypted and can reveal host metadata to clients permitted to reach the configured TCP port (8765 by default). Permit connections only from the SmartThings hub's IPv4 address when practical; otherwise restrict to a private trusted subnet. Never configure router port forwarding. Windows installer `-HubIPv4` optionally scopes its **Private-profile** firewall rule.

**Power operations:** disabled by default. They require explicit opt-in on the host and in SmartThings and a shared random 256-bit key. HMAC-SHA256 binds short-lived single-use challenge nonces to the operation; challenges and authenticated HTTP still traverse a non-TLS local transport. Keep `control-token` and the SmartThings preference confidential, and remember that the hub/account can initiate a power action if compromised.

**No guarantees about sleep or electrical power:** Windows native power API requests can be refused or delayed; `HTTP 202` only acknowledges scheduling. Wake-on-LAN magic packets are unauthenticated at the network layer, and cannot guarantee resuming a given hardware power state, especially Windows S4/S5/Fast Startup. SmartThings may infer stopped/suspended from a timeout; this isn't a physical measurement.

**Tester reports:** do not share host UUIDs, private IPs, MAC addresses, hostnames, SmartThings account/location IDs, HMAC signatures/nonces, screenshots with identifying fields, or raw `journalctl`/Windows event logs. Windows sanitized collector and Linux `beta-report.sh` avoid known identifiers, but **manually review** their output. The Windows WOL diagnostic script can display MAC addresses.

The Windows Service runs as `NT AUTHORITY\LocalService` with ACL-protected state; Linux uses a restricted `linuxhost` account and a separately restricted power-helper socket. Neither implementation is independently security-certified. Installation should be limited to consented test hardware, not critical or production systems.

**Authentication-key clipboard:** The optional Windows wizard only copies the key after an explicit click. Windows clipboard history and synchronization may nevertheless retain the key; users should clear clipboard history and avoid placing it in screenshots, support requests or public logs. The stabilization branch also resets existing token-file ACLs on upgrade; this is not retroactively present in v0.5.4-beta.1.

**Logs:** The stabilization Edge driver avoids printing raw discovered MAC/IP/UUID identifiers during routine discovery and WOL messages. Redaction and firewall scoping do not turn plain HTTP into confidential transport; use the trusted-LAN requirement regardless.
