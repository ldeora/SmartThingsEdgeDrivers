# Computer Host LAN — security and responsible use

**Current architecture:** Linux and Windows agents with SmartThings Edge over the local `computer-host-agent` protocol v2. This page describes the published v0.5.6-beta.1 design and the accepted limitations for the planned v1.0 release; it is **not** an independent security audit, a claim of complete hardware verification, or a guarantee that every protection has been exhaustively tested. See [PROTOCOL.md](PROTOCOL.md), [INSTALLATION.md](INSTALLATION.md), and [v1.0 release gates](docs/release/V1-RELEASE-GATES.md). Older Linux-only v0.3.x notes are preserved for historical reference in [SECURITY-HARDENING.md](SECURITY-HARDENING.md).

## Supported trust model

Use **only on a trusted private LAN**. The computer agent listens on TCP 8765 by default (or a configured alternative), and the SmartThings hub connects to it using **unencrypted HTTP**. It does not require forwarding a port from the public Internet. Where practical, permit incoming agent HTTP traffic **only from the SmartThings hub's LAN address**; allow DNS-SD/mDNS discovery as required by the network. Do not disable firewalls globally or open a public/Internet-facing rule to make discovery work.

The Windows installer offers a Private-profile firewall rule scoped to the selected hub address; a broader Private LocalSubnet fallback requires explicit selection. It does not automatically configure Public-profile access. Linux firewall configuration depends on the host distribution and local administrator. If the hub IP address changes, a Windows allow-list may need an intentional update.

The unauthenticated read-only endpoints `/v2/info`, `/v2/health`, and `/v2/metrics` can disclose hostname, installation UUID, OS and system telemetry to any client that can reach the listening port. HMAC authentication for power operations **does not encrypt or authenticate the monitoring channel**, and it does not authenticate mDNS advertisements. An attacker with sufficient LAN access could observe or interfere with monitoring or disrupt connectivity; network isolation remains necessary.

## Power commands and credentials

- **Monitoring only by default.** Shutdown, reboot and suspend are optional and require enabling power control on the host *and* setting `allowPowerCommands` plus the matching control key on the SmartThings device.
- The agent generates a **random 256-bit control secret** represented as 64 hexadecimal characters. The host protects its persisted copy using OS file permissions/ACLs. The matching copy in a **SmartThings device preference is sensitive configuration data, not a secure vault**; its access and retention are governed by the platform.
- Requests for `/v2/power/{shutdown,reboot,suspend}` use HMAC-SHA256, a short-lived one-use challenge nonce and a fixed list of supported actions. The secret itself is not sent as the HTTP request body. Challenge requests and signed traffic still travel over plain HTTP.
- HTTP **202 is an acknowledgement of the platform-specific acceptance point, not proof that the computer has completed a power-state transition**. On Linux, it follows successful queuing of a non-blocking systemd job. On Windows, shutdown/reboot 202 follows a successful native API call; suspend 202 means the service queued its delayed attempt. Unsaved Windows applications can keep a graceful shutdown pending. Timeouts and host reachability cannot prove physical shutdown, sleep or wake. Never blindly retry a power command that may already have been accepted.
- Wake-on-LAN uses **unauthenticated network magic packets**. Supported sleep and shutdown states depend on the network adapter, driver, firmware and OS; Windows Fast Startup, Modern Standby and S5 wake are not universal capabilities.

## Platform-specific containment

**Linux:** The normal agent runs as the restricted `linuxhost` user, with the opt-in privileged power actions delegated through a restricted systemd socket to a minimal helper. The helper checks the connecting process's UID, resolves `systemctl` from fixed standard system directories at startup, and accepts only the three fixed operations. It runs `systemctl --no-block` and replies `OK` only after systemd confirms that the job was queued; an unavailable executable or rejected/failed job is reported to the HTTP agent as an error (503). Linux firewall, systemd security features, SELinux/AppArmor and WOL persistence must be validated on the intended distribution.

**Windows:** The agent runs as `NT AUTHORITY\\LocalService` with access controls on persistent state and a service-specific security boundary for its token files. A privilege preflight can disable advertised power actions without taking monitoring offline if host policy prevents the necessary operations. Shutdown/reboot call the native Windows API before returning 202; `ERROR_SHUTDOWN_IN_PROGRESS` is reported as HTTP 409 and other immediate native failures as HTTP 503. The API is called without forcing applications closed, so unsaved work can keep shutdown pending until the console user responds. Suspend retains a delayed background attempt so the HTTP response can leave before the machine sleeps; its 202 does not prove that sleep succeeded. The installer and agent in v0.5.6 are **unsigned**. Checksums verify downloaded file content but do not authenticate the publisher in the same way as a trusted code signature.

Neither platform implementation is independently security-certified. Do not infer complete Windows or distro coverage from container tests or Windows Server CI alone.

## Key handling and recovery policy for v1.0

Existing **installation UUIDs and control keys must be preserved across normal upgrades**, along with the existing SmartThings computer device. Never delete persistent state, uninstall-and-purge, or reset credentials merely to fix a failed upgrade.

There is **no automatic key rotation or automatic pairing protocol planned for v1.0**. We are deliberately not introducing a mechanism that might unexpectedly replace a working credential. If the key is missing or incorrect, monitoring can still work while authenticated power commands remain unavailable. Verify the configuration before making changes; do not print or publish the key in troubleshooting logs.

If a key is **suspected compromised**, first disable power control on the host and in SmartThings, restrict network access and investigate the exposure. Do not treat re-copying the same exposed key as a security fix. Any manual credential replacement must be a deliberate, coordinated recovery operation with a validated backup and preservation of the stable installation UUID; no automatic or untested rotation procedure is offered in this release.

Treat screenshots, exported preferences, clipboard history, synchronised clipboard, Windows Event Logs, journal output, diagnostic ZIPs, private IPv4 addresses, MAC addresses, installation UUIDs and SmartThings account/location identifiers as potentially sensitive. Review even sanitized reports manually before sharing. The Windows installer copies a control key to the clipboard only after an explicit user action.

## Reporting a security concern

Do **not** post real credentials, privately identifying diagnostics, or proof-of-exploit details in a public GitHub issue or Community thread. If GitHub's **private vulnerability reporting** option is enabled for this repository, use it for sensitive reports. Otherwise, use a non-sensitive public request asking the maintainer for a private reporting channel, without disclosing exploit steps or secrets. For ordinary installation problems, file a redacted issue with OS version, agent/driver version and a concise description.

## Release limitations and open decisions

The v1.0 acceptance checklist separately requires review of third-party redistribution notices, final build integrity/provenance, signing policy, Windows/Linux installation and upgrade recovery, and real hardware behavior. These remain **release gates**, not claims already satisfied. TLS/mTLS, automatic pairing and routine key rotation are out of scope for v1.0.
