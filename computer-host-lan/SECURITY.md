# Computer Host LAN — security and responsible use

**Scope and version:** Computer Host LAN uses local `computer-host-agent` protocol v2 on Linux and Windows. This page describes **published v1.0.0-rc.2** (Linux/Edge 0.4.6-rc.2, Windows 0.2.7-rc.2; [release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2), source commit `72e4a99c4b2e8f958ce771152826319318d0d537`). The published rc.1 binaries **do not include the later security fixes**; its post-rc.1 hardening is present in rc.2 only. Publication is not independent security certification or completion of physical Windows 11 acceptance. See [PROTOCOL.md](PROTOCOL.md), [INSTALLATION.md](INSTALLATION.md), [release gates](docs/release/V1-RELEASE-GATES.md) and earlier Linux notes in [SECURITY-HARDENING.md](SECURITY-HARDENING.md).

## Known issues in the published rc.1

**Version-specific security notice:** The downloadable **v1.0.0-rc.1** Windows Setup.exe, Windows ZIP and Linux source archive were published on November 20, 2026 **UTC** from tag `5466ad0`, not the current `main` implementation. The fixes below were merged **after** rc.1 and are **included in published rc.2**. They do **not** apply retroactively to the published rc.1 release.

- **Windows retained state and control key ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)):** rc.1 does **not** verify the ownership and access rules of a pre-existing ProgramData state directory before reusing its token, nor create a new directory with the final protected ACL atomically. A less-trusted local Windows account may be able to influence the control key used for authenticated power commands. **Do not enable power control on rc.1 on shared PCs with untrusted local accounts.** A preliminary check of `%ProgramData%\ComputerHostAgent` for unexpected files and ownership is prudent, but **cannot eliminate the fresh-creation race**. Do not delete valid retained state or re-pair the existing SmartThings device. The protection documented in the **Windows** subsection below is included in published rc.2, not rc.1.
- **HTTP reliability ([#30](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/30), [#31](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/31)):** rc.1 does not include the corrected Edge-driver HTTP timeout enforcement or the cumulative Linux HTTP-header deadline behavior introduced in PR #56; unresponsive or slow connections can behave differently.
- **Power acknowledgments ([#33](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/33), [#44](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/44)):** rc.1 lacks PR #57's Windows native shutdown/reboot acceptance/error mapping and Linux executable validation and delayed power-off/reboot attempt. The detailed HTTP 409/503 and one-second grace-period semantics stated below apply to `main`, **not rc.1**.
- **Network diagnostics ([#46](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/46)):** rc.1 does not include the additional Windows Public-network warning introduced on `main` in PR #59. All releases continue to require an appropriately configured trusted private LAN.

Use the published rc.1 **only with its documented limitations**; prefer published rc.2 when testing the post-rc.1 fixes. Neither GitHub publication nor green CI replaces physical hardware acceptance.

## Supported trust model

Use **only on a trusted private LAN**. The computer agent listens on TCP 8765 by default (or a configured alternative), and the SmartThings hub connects to it using **unencrypted HTTP**. It does not require forwarding a port from the public Internet. Where practical, permit incoming agent HTTP traffic **only from the SmartThings hub's LAN address**; allow DNS-SD/mDNS discovery as required by the network. Do not disable firewalls globally or open a public/Internet-facing rule to make discovery work.

The Windows installer offers a Private-profile firewall rule scoped to the selected hub address; a broader Private LocalSubnet fallback requires explicit selection. It does not automatically configure Public-profile access. Linux firewall configuration depends on the host distribution and local administrator. If the hub IP address changes, a Windows allow-list may need an intentional update.

The unauthenticated read-only endpoints `/v2/info`, `/v2/health`, and `/v2/metrics` can disclose hostname, installation UUID, OS and system telemetry to any client that can reach the listening port. HMAC authentication for power operations **does not encrypt or authenticate the monitoring channel**, and it does not authenticate mDNS advertisements. An attacker with sufficient LAN access could observe or interfere with monitoring or disrupt connectivity; network isolation remains necessary.

**Post-rc.2 Linux implementation (intended rc.3):** In addition to the existing
12-handler global limit and absolute five-second header deadline, a single
source IP can hold at most four active HTTP handlers. Excess connections are
closed before a handler thread is started. Source IPs shared by several
clients share this limit; ordinary serial requests and up to four concurrent
connections remain supported. This mitigates one source monopolizing the
global handler pool, not distributed saturation, listen-backlog pressure or
other LAN interference. No authentication, rate guarantee or firewall
policy is added. The published rc.2 packages do not contain this per-source
limit.

**Post-rc.2 Edge implementation (intended rc.3):** The existing four-second
socket inactivity timeout is supplemented by an eight-second budget per
HTTP request. The driver bounds each cooperative cosock readiness wait,
including repeated waits inside a single read or write, and closes its
owned connection on expiry. Agent responses are still capped at 32 KiB;
redirects are not followed. Challenge and signed POST have separate
budgets, and an expired power request may already have been accepted.
Do not blindly retry. This is a cooperative transport deadline, not a
preemptive limit on synchronous DNS resolution or other non-yielding
runtime work, nor a monotonic real-time guarantee under clock changes.
A detected incompatible scheduler yield is relayed unchanged to finish the
same request; a one-time error records that the cumulative budget is disabled
until driver restart, with the original inactivity timeout retained. An
unavailable initial deadline clock/select also triggers the compatibility
path. There is no automatic retry, including for signed POST. This is a
limited compatibility safeguard, not protection against arbitrary runtime
incompatibility; fallback is a failed qualification. #177 merged after native
CI and scoped V4 hub qualification; exact rc.3 acceptance remains required.

**Post-rc.2 discovery implementation (intended rc.3, #124):** A known
responsive endpoint returning the expected installation UUID from health
wins over a competing discovery candidate. When the known endpoint cannot
be confirmed, discovery can select a matching candidate; the driver retains
cached WOL metadata and requires a matching normal health poll before
refreshing it or sending power POSTs to the new automatic endpoint. Explicit
host overrides prevent automatic endpoint updates. This is a conservative
selection heuristic, not authentication of discovery, UUID, telemetry or
WOL metadata: a reachable untrusted responder at the known address, or one
selected while the genuine host is unavailable, can still mislead monitoring.
A competing candidate may add one bounded health request; rediscovery is
not a single globally bounded HTTP transaction. Use a trusted private LAN
and explicit override where appropriate. Published rc.2 does not include
these changes.

## Power commands and credentials

- **Monitoring only by default.** Shutdown, reboot and suspend are optional and require enabling power control on the host *and* setting `allowPowerCommands` plus the matching control key on the SmartThings device.
- The agent generates a **random 256-bit control secret** represented as 64 hexadecimal characters. The host protects its persisted copy using OS file permissions/ACLs. The matching copy in a **SmartThings device preference is sensitive configuration data, not a secure vault**; its access and retention are governed by the platform.
- Requests for `/v2/power/{shutdown,reboot,suspend}` use HMAC-SHA256, a short-lived one-use challenge nonce and a fixed list of supported actions. The secret itself is not sent as the HTTP request body. Challenge requests and signed traffic still travel over plain HTTP.
- HTTP **202 is an acknowledgement of the platform-specific acceptance point, not proof that the computer has completed a power-state transition**. On Linux, shutdown/reboot 202 means the helper accepted a delayed attempt; the systemd job is invoked after a one-second grace period so the agent can reply before shutdown stops its services. Linux suspend 202 means the systemctl command returned success, not that the host is asleep. On Windows, shutdown/reboot 202 follows a successful native API call; suspend 202 means the service queued its delayed attempt. Unsaved Windows applications can keep a graceful shutdown pending. Timeouts and host reachability cannot prove physical shutdown, sleep or wake. Never blindly retry a power command that may already have been accepted.
- Wake-on-LAN uses **unauthenticated network magic packets**. Supported sleep and shutdown states depend on the network adapter, driver, firmware and OS; Windows Fast Startup, Modern Standby and S5 wake are not universal capabilities.

## Platform-specific containment

**Linux:** The normal agent runs as the restricted `linuxhost` user, with the opt-in privileged power actions delegated through a restricted systemd socket to a minimal helper. The helper checks the connecting process's UID, resolves `systemctl` from fixed standard system directories at startup, and accepts only the three fixed operations. It uses `systemctl --no-block` for all actions. For shutdown/reboot, it replies `OK` first, gives the HTTP agent one second to respond, and then attempts the systemd command; failures after this acknowledgment cannot be reported to the hub. For suspend, it waits for the command to return success before replying `OK`, and reports an immediate command error as HTTP 503. Missing or inaccessible executables are rejected before the acknowledgment. Delay inhibitors or later systemd failures can defer or prevent a power transition even after acknowledgment. Linux firewall, systemd security features, SELinux/AppArmor and WOL persistence must be validated on the intended distribution.

**Windows:** The agent runs as `NT AUTHORITY\LocalService` with access controls on persistent state and a service-specific security boundary for its token files. A privilege preflight can disable advertised power actions without taking monitoring offline if host policy prevents the necessary operations. Shutdown/reboot call the native Windows API before returning 202; `ERROR_SHUTDOWN_IN_PROGRESS` is reported as HTTP 409 and other immediate native failures as HTTP 503. The API is called without forcing applications closed, so unsaved work can keep shutdown pending until the console user responds. Suspend retains a delayed background attempt so the HTTP response can leave before the machine sleeps; its 202 does not prove that sleep succeeded. The Windows installer creates a new ProgramData state directory with its protected DACL in the directory-creation operation, then verifies it immediately; it does not expose a newly created folder with inherited ProgramData permissions. The published rc.2 installer checks retained state before installation, including ownership, allow ACEs and reparse points. In rc.3, the agent also checks the protected directory, installation identity and boot-session files before startup use. A missing or unsafe state directory is not created by the agent; unsafe identity or boot state causes startup refusal. A missing, unreadable, malformed or unsafe control-token disables power only, provided identity and monitoring state remain safe. The agent never fixes ACLs or regenerates a power key. These are startup/use-boundary checks, not continuous ACL monitoring or protection from concurrent trusted administrator changes; restart the agent after correcting the state. Existing published rc.2 binaries do not include these runtime checks. The directory and control-token are restricted to administrators/SYSTEM and the exact ComputerHostAgent service SID; LocalService and that service SID are accepted as owners only for agent-created state files. Untrusted ownership, unexpected allow rules or a reparse-point redirect cause a fail-closed refusal. Normal upgrades preserve the same key and UUID. Windows installer and agent binaries in rc.2 and rc.3 are **unsigned**. Checksums verify downloaded file content but do not authenticate the publisher in the same way as a trusted code signature.

Neither platform implementation is independently security-certified. Do not infer complete Windows or distro coverage from container tests or Windows Server CI alone.

## Key handling and recovery policy for v1.0

Existing **installation UUIDs and control keys must be preserved across normal upgrades**, along with the existing SmartThings computer device. Never delete persistent state, uninstall-and-purge, or reset credentials merely to fix a failed upgrade.

There is **no automatic key rotation or automatic pairing protocol planned for v1.0**. The installer never silently replaces a working credential. If the key is missing or incorrect, monitoring can still work while authenticated power commands remain unavailable. Verify the configuration before making changes; do not print or publish the key in troubleshooting logs.

If a key is **suspected compromised**, first disable power control on the host and in SmartThings, restrict network access and investigate the exposure. Do not treat re-copying the same exposed key as a security fix. A deliberate manual replacement must preserve the stable installation UUID: restore the state directory's trusted ACLs, remove only the compromised `control-token`, run Setup with power management enabled to generate a new key, and update the SmartThings device's `controlKey` preference before re-enabling `allowPowerCommands`. Never purge the whole state directory as a key-rotation shortcut. See [INSTALLATION.md](INSTALLATION.md) for the first-install orphan recovery path.

Treat screenshots, exported preferences, clipboard history, synchronised clipboard, Windows Event Logs, journal output, diagnostic ZIPs, private IPv4 addresses, MAC addresses, installation UUIDs and SmartThings account/location identifiers as potentially sensitive. Review even sanitized reports manually before sharing. The Windows installer copies a control key to the clipboard only after an explicit user action.

## Reporting a security concern

Do **not** post real credentials, privately identifying diagnostics, or proof-of-exploit details in a public GitHub issue or Community thread. If GitHub's **private vulnerability reporting** option is enabled for this repository, use it for sensitive reports. Otherwise, use a non-sensitive public request asking the maintainer for a private reporting channel, without disclosing exploit steps or secrets. For ordinary installation problems, file a redacted issue with OS version, agent/driver version and a concise description.

## Release limitations and open decisions

The v1.0 acceptance checklist separately requires review of third-party redistribution notices, final build integrity/provenance, signing policy, Windows/Linux installation and upgrade recovery, and real hardware behavior. These remain **release gates**, not claims already satisfied. TLS/mTLS, automatic pairing and routine key rotation are out of scope for v1.0.

### Windows connection admission (prospective rc.3)

Kestrel retains its global limit of twelve connections and five-second header
deadline. Connection middleware before HTTP parsing admits at most four
active connections per remote IP (IPv4-mapped IPv6 normalized to IPv4).
Excess connections are aborted, not queued by this middleware. This reduces
single-source saturation; it is not authentication or protection against
distributed saturation, shared-source contention or transport backlog pressure.

### rc.3 Linux distribution and maintenance

The standalone installer uses a fixed embedded trusted payload and protected
transaction engine. It requires explicit confirmation before modifying agent
files or installer-owned NIC policy. Retained rc.2 state requires explicit
reuse consent and validation; historical restoration validates root-private
local backups and keeps current credentials. A local backup digest is not a
publisher signature. Normal uninstall preserves identity/key and backups.
See [maintenance journeys](docs/release/UPGRADE.md). See the release evidence for physical acceptance; implementation alone does not establish hardware compatibility.

The maintainer's November 26 release-scope decision retains unsigned packages
for rc.3 and v1.0 and defers formal signing/independent attestation approval
and notice automation to v1.2. Use exact-source release assets, SHA-256 and
build metadata; checksums do not independently authenticate the publisher.
Do not disable platform protections or substitute ordinary CI artifacts.
Applicable third-party redistribution obligations remain. No release or
security acceptance is implied by this decision.
