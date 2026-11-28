---
name: Computer Host LAN bug report
about: Report monitoring, discovery, installation or power problems in Computer Host LAN (Linux/Windows)
title: "[Computer Host LAN] "
---

**Before posting:** This repository and its issues are public. Do **not** share the control token, HMAC nonce/signature, installation UUID, IP or MAC address, personal hostname, SmartThings account/location IDs, or unredacted logs/screenshots. Review diagnostics manually.

### Environment

- Integration version / GitHub release:
- Host agent version (Linux or Windows):
- SmartThings Edge Driver version:
- OS and version/build (Linux distro or Windows 11):
- CPU architecture:
- Hub model / firmware:
- Ethernet or Wi-Fi (without identifying adapter information):
- Networking factors (multiple NICs, VPN, isolation, multicast) if relevant:

### Test and reproduction

- Relevant test ([checklist](../../computer-host-lan/docs/testing.md)):
- Monitoring only / opted into power:
- Steps to reproduce:
- Expected result:
- Actual result:
- Happens after restart/reboot?:
- Relevant Windows `powercfg /a` state, if power issue (redacted):
- Recovery/workaround:

### Sanitized evidence

Attach **only** manually reviewed `Collect-WindowsDiagnostics.ps1` output or Linux `beta-report.sh` results. Never attach raw control requests, unredacted driver logs, or secrets.

**Safety:** Power and Wake-on-LAN remain experimental and may depend on NIC, firmware, Windows Fast Startup and LAN topology. Do not conduct destructive tests on production or remotely unrecoverable PCs.
