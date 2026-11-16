> **Latest changes:** See [SECURITY-HARDENING.md](SECURITY-HARDENING.md).

# Security notes (historical baseline; see SECURITY-HARDENING.md for v0.3.0)

**Development preview: not security-audited.** The daemon listens over
unencrypted HTTP by default, and read-only info/health/metrics are visible to
anyone with network access to TCP 8765. Do not forward it through a router,
expose it to the Internet, or deploy it on an untrusted Wi-Fi/LAN.

## Controls already implemented

- Power endpoints are disabled by default and enabled only via the
  `--enable-power-control` agent flag (installed with the optional systemd
  drop-in); the SmartThings
  switch additionally requires `allowPowerCommands=true` and a configured key.
- The agent generates a random **256-bit secret** and stores it in a private
  state file (`0600`, owned by the dedicated agent user).
- Power commands use **HMAC-SHA256**, not a plaintext token over HTTP. A
  one-time random 192-bit nonce expires after 30 seconds after successful
  signature checking (v0.3.0). Commands and paths are included in the signature.
- Only hard-coded `shutdown`, `reboot`, and `suspend` requests are accepted.
  Arbitrary commands, filenames and shell strings are never evaluated.
- The agent runs as an unprivileged `linuxhost` user; privileged actions are
  delegated via a restricted Unix socket to a minimal root helper, which also
  checks the calling process UID using `SO_PEERCRED`.
- Linux systemd unit has filesystem and namespace hardening options. The
  helper uses fixed `/usr/bin/systemctl` arguments without `shell=True`.
- The Edge driver never intentionally logs the control secret or HMAC value.

## Remaining security limitations

- **No TLS or mutual authentication of the HTTP server.** HMAC authenticates a
  command to the target but cannot protect telemetry, host metadata, or
  challenge/signature traffic against eavesdropping. A LAN attacker capable of
  MITM or active races may cause denial-of-service or more. Use VLAN/firewall
  isolation and do not rely on HMAC as full channel security.
- The shared secret is entered into a **SmartThings device preference**, which
  may be retained by the platform. Treat it as sensitive account/configuration
  data, not as a local secure enclave. A compromised SmartThings account or hub
  can operate the computer.
- Host info and telemetry are **unauthenticated**. They reveal hostname, OS,
  uptime, hardware metrics and the installation UUID to LAN clients.
- Magic packets are unauthenticated by the WOL protocol; anyone on the LAN
  who can send them may also attempt to wake the system.
- If a power request times out after reaching the agent, the command may
  already have been executed; the sender must not retry blindly.
- A root-side helper that accepts power actions can still cause data loss if
  misused. Ordinary systemd power actions should be graceful but applications
  may still have unsaved work.
- The socket helper's systemd integration and all hardening settings need
  testing on the supported distributions.

## Recommended deployment

1. Use a trusted VLAN. Permit **TCP 8765 only from the SmartThings hub** where
   practical, and permit mDNS as needed. No WAN port forwarding.
2. Enable WOL in the OS/firmware only when needed. Disable remote power
   actions unless explicitly required.
3. Keep the control key private. Do not publish it in SmartThings screenshots,
   diagnostic archives, bug reports or documentation.
4. Rotate compromised keys by stopping the agent, generating a new token,
   restarting, and updating the device preference; do not delete the stable
   installation ID in the process.
5. Before a public release, add automated systemd integration tests, perform a
   third-party security review, and consider a mutually authenticated TLS
   transport or local certificate pinning.

## Network-interface selection (agent 0.2.2)

Automatic WOL interface selection is based on the host network configuration and /sys physical-device topology. For computers with more than one candidate NIC or complex network routes, explicitly choose the WOL-capable Ethernet NIC via `--wol-interface` or `LINUX_HOST_WOL_INTERFACE`. This affects only advertised WOL metadata; it grants no additional privileges. Port 8765 remains LAN-only, power commands still require HMAC authentication, and the agent continues running unprivileged.

## v0.2.9 installer and diagnostic security

- `scripts/diagnose.sh` is read-only and avoids displaying the UUID, MAC and
  broadcast address in the general-agent summary, never the HMAC token. An
  opt-in `ethtool` interface check displays only WOL flags. Review output
  before publishing because host/kernel names still may be identifying.
- Fresh monitoring-only installs no longer enable the privileged
  `linux-host-agent-power.socket`; existing power-enabled installations
  retain their opt-in drop-in and socket.
- WOL persistence changes are opt-in. The systemd-udev `.link` file is
  specific to one MAC; the NetworkManager alternative affects only the
  selected connection. Neither installer opens firewall ports.
- HMAC over **plain HTTP is not encrypted transport**. The secret is not
  transmitted directly, but health/metrics can be observed/interfered with by
  parties who control the network. Do not use an untrusted LAN, route port
  8765 over the Internet, or distribute any actual `control-token` file.
- A compromised SmartThings account with read access to device preferences
  may expose the control key. The control-key preference is not equivalent
  to a hardware-backed secret vault.
- Signed acceptance does not guarantee the target actually completed a
  shutdown/reboot/suspend. `stopped`/`suspended` remain inferred statuses.
