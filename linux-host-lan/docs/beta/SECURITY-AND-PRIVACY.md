# Security, privacy and operational boundaries

The agent runs an HTTP listener on TCP/8765 using the local network, not HTTPS. A network observer may see host metadata and monitoring values. Power requests use HMAC-SHA256 signatures and short-lived one-time nonces, but **HMAC is not network encryption**. For the beta, only install on a trusted LAN and restrict incoming TCP/8765 to the SmartThings hub (and a specific trusted administrator if required).

The read-only `/v1/info` endpoint reveals hostname, OS name, agent installation identity and Wake-on-LAN metadata. Do not expose it to the internet. Do not forward TCP/8765 on a router. The installer does not automatically configure a firewall or proxy.

The standard agent runs unprivileged as `linuxhost`. Optional shutdown/reboot/suspend use a separate root-owned helper over a Unix socket, accept only three fixed power actions and require an explicit opt-in. The sensitive HMAC key is stored locally under `/var/lib/linux-host-agent/control-token` and entered into the SmartThings device configuration; treat both copies as secrets. Never transmit the key to testers or include it in diagnostics.

The Linux agent does not need external APIs for its local network endpoints. The SmartThings hub and platform may synchronize device attributes and history through the normal SmartThings service. Testers should review SmartThings' own privacy policies independently.

Do not enable remote power control for a machine where abrupt or unexpected power transitions could cause harm. The device may have disks mounted, jobs running, unsaved work or services used by others. Host status following an unacknowledged network outage is an inference, **not cryptographic proof of shutdown or suspend**.

Review required before unrestricted public release: independent source audit, network abuse tests, limits verification, credential rotation model, package file ownership, kernel/systemd privilege constraints, SELinux/AppArmor compatibility and a verified signed-release process.
