# Security and privacy

Computer Host LAN is designed for a trusted private LAN, not an Internet-facing
service. These are the current protocol-v2 guarantees and limitations. Use the
[versioned release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3) and its matching instructions.

## Network and data

| Traffic | Direction / purpose | Protection |
| --- | --- | --- |
| UDP 5353 (mDNS/DNS-SD) | Local discovery | Unauthenticated |
| TCP 8765 by default (HTTP) | Hub → agent; info, health, metrics | Plain HTTP, unauthenticated reads |
| TCP agent port (HTTP) | Hub → agent; challenge and power requests | HMAC-SHA256 on power requests; not encrypted |
| UDP 9 by default (WOL) | Hub → LAN; magic packet | Unauthenticated |

The read endpoints can disclose hostname, installation UUID, OS, network
metadata and system measurements to clients that can reach the agent.
HMAC does not authenticate discovery, protect monitoring integrity or provide
confidentiality. The hub communicates locally with the agent; SmartThings
itself still uses its platform services. No additional cloud service is
required.

Restrict HTTP access to the hub's LAN address where practical; allow local
discovery. Never forward the port to the Internet or disable firewalls to
make discovery work. Windows Setup offers a Private-profile hub-scoped rule
or an explicitly selected Private LocalSubnet fallback. It does not open a
Public-profile rule. Linux firewall configuration remains the administrator's
responsibility. See [network troubleshooting](docs/troubleshooting.md#firewall-and-avahi).

Both agents limit concurrent connections globally (12) and per source (4),
with five-second cumulative header deadlines. The Edge driver uses a
four-second inactivity timeout and an eight-second cooperative HTTP request
budget; response size is capped at 32 KiB and redirects are not followed.
These limits mitigate resource exhaustion, not authentication or protection
from distributed saturation, shared-source contention, DNS rebinding or
all LAN interference. The cooperative deadline has a compatibility fallback
to inactivity-only behavior and is not a preemptive DNS/runtime deadline.
Automatic discovery prefers a responsive known matching endpoint and requires
health confirmation after migration before power POSTs or WOL metadata
refresh. This does not authenticate the endpoint or the advertised UUID.

## Power and credentials

Monitoring is enabled by default; shutdown, reboot and suspend require host
opt-in, device opt-in and the matching 256-bit secret (64 hexadecimal
characters). Power requests use a short-lived, single-use challenge nonce
and HMAC-SHA256 over the protocol's defined fields; the key itself is not
transmitted in the request body. The host stores it with restricted OS
permissions. SmartThings preferences are sensitive configuration data,
not a secure vault.

An HTTP 202 acknowledges acceptance at the platform's implementation point,
not completed physical power transition. Linux shutdown/reboot accepts a
delayed attempt before invoking systemd; Windows shutdown/reboot acknowledges
successful native request acceptance, and suspend queues a delayed attempt.
Linux suspend acknowledges successful systemctl invocation. Errors after
acceptance may not reach the hub. Save work and keep physical access.
Do not retry a request whose acceptance is uncertain. WOL uses no key and
depends on hardware. See [Host Status](docs/smartthings.md#host-status-and-the-switch).

## Host containment and maintenance

- **Linux:** the agent runs under the restricted `linuxhost` account.
  Optional power requests use a restricted systemd socket and a minimal
  helper checking peer UID and allowing only fixed actions, using validated
  systemctl from standard system directories. The protected standalone
  installer requires reviewed explicit consent and authorization. It
  refuses ambiguous ownership/state or network policy rather than
  overriding it, keeps identity and key across ordinary upgrades, and
  validates retained state and eligible local snapshots. A backup digest is
  not a publisher signature. Normal removal retains recovery material.
- **Windows:** the service runs as LocalService with access restricted by
  its exact service SID. New state directories are created with protected
  ACLs; existing directories and files are checked for trusted ownership,
  allow rules and reparse points. Unsafe identity/boot state refuses startup;
  an unsafe, malformed, unreadable or missing key disables power if
  monitoring state is otherwise safe. These are use-boundary checks, not
  continuous ACL monitoring. The agent does not silently repair ACLs or
  regenerate keys. Power privilege checks can leave monitoring available
  with power disabled.

Neither implementation is independently security-certified. See
[maintenance](docs/upgrade.md) before repairing, reinstalling or removing
an agent. Never purge valid identity or delete protected journals to force
an upgrade.

## Key handling and suspected compromise

Do not publish control keys, nonces, signatures, UUIDs, addresses, MACs,
hostnames or account/location identifiers. Review screenshots, clipboard
history, exported preferences, diagnostics and logs before sharing, even
when a diagnostic tool is designed to redact them.

If a key may have been exposed, disable power on the host and in SmartThings,
restrict network access and investigate. Re-copying the same compromised key
does not restore security. There is no automatic rotation or pairing
protocol. Seek maintainer guidance for deliberate replacement while
preserving identity; do not delete the whole state directory or bypass
protected installer state. In particular, do not remove a Linux key or
protected journal simply to force regeneration.

## Package integrity

Verify SHA-256 against the matching trusted published release. Linux and
Windows installers are unsigned; normal releases lack independent artifact
attestation. Checksums verify content, not publisher identity. Do not bypass
platform protections or elevate ordinary CI artifacts or development source
scripts. See [third-party notices](docs/THIRD-PARTY-NOTICES.md). Signing,
attestation, TLS and automatic key management are not current features.

## Reporting a security concern

Use GitHub private vulnerability reporting if enabled. Otherwise ask the
maintainer for a private reporting channel in a non-sensitive public message.
Do not post exploit details, credentials or identifying diagnostics in public.
For ordinary bugs use [troubleshooting and reporting](docs/troubleshooting.md#reporting-a-problem).

## Known issues in the published rc.1

The published rc.1 binaries **do not include the later security fixes**.

**Version-specific security notice:** The downloadable **v1.0.0-rc.1** Windows Setup.exe, Windows ZIP and Linux source archive were published on November 20, 2026 **UTC** from commit `5466ad0`, not the current `main` implementation. The fixes below were merged **after** rc.1 and are included in published rc.2 and later releases. They do **not** apply retroactively to the published rc.1 release.

- **Windows retained state and control key ([#32](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/32)):** rc.1 does **not** verify the ownership and access rules of a pre-existing ProgramData state directory before reusing its token, nor create a new directory with the final protected ACL atomically. A less-trusted local Windows account may be able to influence the control key used for authenticated power commands. **Do not enable power control on rc.1 on shared PCs with untrusted local accounts.** A preliminary check of `%ProgramData%\ComputerHostAgent` for unexpected files and ownership is prudent, but **cannot eliminate the fresh-creation race**. Do not delete valid retained state or re-pair the existing SmartThings device. The protection documented in the **Windows** subsection below is included in published rc.2, not rc.1.
- **HTTP reliability ([#30](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/30), [#31](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/31)):** rc.1 does not include the corrected Edge-driver HTTP timeout enforcement or the cumulative Linux HTTP-header deadline behavior introduced in PR #56; unresponsive or slow connections can behave differently.
- **Power acknowledgments ([#33](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/33), [#44](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/44)):** rc.1 lacks PR #57's Windows native shutdown/reboot acceptance/error mapping and Linux executable validation and delayed power-off/reboot attempt. The detailed HTTP 409/503 and one-second grace-period semantics stated below apply to the current release, **not rc.1**.
- **Network diagnostics ([#46](https://github.com/ldeora/SmartThingsEdgeDrivers/issues/46)):** rc.1 does not include the additional Windows Public-network warning introduced after rc.1. All releases continue to require an appropriately configured trusted private LAN.

Use the published rc.1 **only with its documented limitations**; prefer the current published release. Neither GitHub publication nor green CI replaces physical hardware acceptance.

For the complete version-matched historical security and transport details,
see the [rc.3 tagged security reference](https://github.com/ldeora/SmartThingsEdgeDrivers/blob/computer-host-lan-v1.0.0-rc.3/computer-host-lan/SECURITY.md).
