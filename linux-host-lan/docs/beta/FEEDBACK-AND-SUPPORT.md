# Beta feedback and bug report protocol

## What to send

1. The result of `./scripts/beta-report.sh` (review before publishing).
2. SmartThings Edge Driver version and Linux Agent version (not installation ID).
3. Which feature was attempted and exactly what happened; expected versus actual.
4. Whether it reproduces; approximate elapsed time and number of failed polls.
5. Whether the system uses NetworkManager, systemd-networkd, SELinux, AppArmor or a firewall.
6. Whether WOL worked before/after a **reboot** and whether it was suspend versus full shutdown.
7. Only the relevant, **manually redacted** log lines if needed.

## Do not share

Never post `/var/lib/linux-host-agent/control-token`, HMAC signatures/nonces, raw power HTTP requests, LAN IP addresses, NIC MACs, device IDs, personal hostnames, SmartThings account/location IDs, unredacted journal exports, or full network profiles. Screenshots can reveal user names, home names or device IDs—review them first.

The beta report tool intentionally prints no tokens, hostnames, MACs, addresses, installation UUIDs or SmartThings IDs. It cannot sanitize other files you decide to attach.

## Bug report template

```text
Linux Host beta integration version:
Agent version:
Edge Driver version:
Distribution / version:
Kernel:
Python:
Systemd / networking manager:
Read-only monitoring or power-control issue:
Steps to reproduce:
Expected:
Observed:
Does it happen after an agent restart / hub reboot / host boot?:
WOL-capable Ethernet? (yes/no/not tested):
Relevant SANITIZED logs:
```

Support channels and issue tracker URLs will be published by the maintainer; they are intentionally not invented here.
