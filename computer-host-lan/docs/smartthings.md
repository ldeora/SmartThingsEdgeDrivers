# SmartThings setup and device reference

Computer Host LAN uses a SmartThings Edge driver and one agent per computer.
Install the [Windows](install-windows.md) or [Linux](install-linux.md) agent.
The hub and host communicate directly on a trusted LAN; SmartThings still
uses its own platform services. See [security and privacy](../SECURITY.md).

## Add a computer

1. Open the [Computer Host LAN channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20),
   sign in with your Samsung account, enroll the hub and install **Computer
   Host LAN** under Available Drivers. This is separate from agent installation.
   Do not use the older protocol-v1 Linux Host LAN driver.
2. With the new computer's agent running, choose **Add device → Scan nearby**
   in the SmartThings app. The driver selects the Linux or Windows profile.
3. Check Host Status and metrics. For an existing installation, refresh its
   device; do not scan again or delete it to fix an upgrade.

Each computer gets its own persistent identity and key. Install a separate
agent on each host and scan for each new computer. Never clone private
installation state between machines. Different protocol-v2 agent versions
are intended to coexist on one hub; older versions may lack some optional
metrics. Upgrade agents individually and retain existing devices.

## What is measured?

| Metric | Linux | Windows |
| --- | --- | --- |
| CPU utilization | Yes | Yes |
| RAM usage %, total, used, available GiB | Yes | Yes |
| Root/system filesystem usage %, total, used, available GiB | Root filesystem | System drive |
| Uptime | Yes | Yes (see [Fast Startup](troubleshooting.md#uptime-looks-too-long-windows)) |
| CPU temperature | When suitable sensor available | No |
| Load averages (1, 5, 15 minutes) | Yes | No |

GiB uses 1024³ bytes. Available filesystem space may exclude reserved space;
Used + Available need not equal Total. Values update on polling, not as an
instantaneous stream.

## Host Status and the switch

The tile shows Host Status, while its power button operates the switch.
The switch acknowledges accepted shutdown or successful WOL transmission
and is also updated by health polling. Host Status describes observation
or inference, not electrical measurement.

| Host Status | Meaning |
| --- | --- |
| Running | The expected agent is responding; after a prolonged power transition the driver can return to this state. |
| Starting | Wake was requested and its packet sent; a successful health poll has not yet confirmed startup. |
| Stopping | Shutdown request was accepted and confirmation is pending. |
| Stopped | After an accepted shutdown, repeated host-unreachable failures meet the threshold; inferred, not proof of power-off. |
| Rebooting | Restart was accepted; a changed boot ID is needed to confirm the new boot. |
| Suspending | Sleep request was accepted and confirmation is pending. |
| Suspended | After an accepted suspend, repeated host-unreachable failures meet the threshold; inferred, not proof of sleep. |
| Unreachable | The agent cannot be reached after repeated failures without sufficient evidence of a particular power transition. |
| Unknown | State cannot safely be inferred, for example after an unexpected protocol/identity error. |

Pending actions expire if not confirmed. An accepted shutdown with the agent
still responding is treated as in progress for 60 seconds; an agent that
keeps responding after that can show Running again. Stopped/Suspended may
persist through continued host silence. A TCP connection refusal generally
means the agent is unavailable, not necessarily that the computer is off;
the switch can remain On. Repeated host timeouts may infer switch Off if the
preference is enabled. Unknown failures do not establish an off state.
See [troubleshooting](troubleshooting.md) if the state seems wrong.

### Routines

Use Switch On to request wake and Switch Off to request shutdown if power
control is enabled. The separate Wake, Restart and Sleep buttons offer
the corresponding operations. Use **Host Status = Running** for a routine
that needs a responding agent; use **Stopped** as an inferred shutdown
outcome, not a safety interlock. Unreachable alone does not distinguish
network failure, a stopped service and a powered-off PC. Save work and keep
physical access before testing power. Never rely on inferred power states
for electrical isolation or a safety-critical automation.

## Optional power control

Enable power on the host using its installer, then enable **Enable
shutdown/reboot/suspend** and enter its private **Power control key (64 hex
chars)** in SmartThings device settings. Monitoring does not require this
key. Wake-on-LAN does not use it; it needs supported hardware and network
settings. Never share keys or screenshots containing them. After enabling
power on a previously monitoring-only computer, the driver may need time
to learn the available actions (about one minute observed on Gentoo, not a
guaranteed maximum). Refresh and verify settings; never blindly repeat a
power request whose acceptance is uncertain.

## Device settings

Defaults and ranges apply to the current Linux and Windows profiles.
Leave overrides empty unless automatic selection needs an intentional
correction.

| Preference (internal name) | Default | Range / purpose |
| --- | --- | --- |
| Availability polling (seconds) (`pollInterval`) | 20 | 10–300; check agent reachability. |
| Telemetry polling (seconds) (`telemetryInterval`) | 60 | 30–3600; update metrics. |
| Static host address (`hostOverride`) | Empty | Optional host:port after initial discovery; IP preferred; no HTTPS. Prevents automatic endpoint updates. |
| WOL MAC override (`wolMacOverride`) | Empty | Target Ethernet MAC, if automatic metadata is missing or wrong. |
| WOL broadcast IPv4 (`wolBroadcastOverride`) | Empty | Override agent-recommended broadcast or fallback 255.255.255.255. |
| WOL UDP port (`wolPort`) | 9 | 1–65535; normally 9 or 7. |
| Enable shutdown/reboot/suspend (`allowPowerCommands`) | false | Requires host opt-in and matching key. |
| Power control key (64 hex chars) (`controlKey`) | Empty | Private 64 hexadecimal characters; preferences are not a secure vault. |
| Unreachable after failed polls (`failureThreshold`) | 3 | 2–10; failures before state inference. |
| Infer Switch Off after timeouts (`assumeOffWhenUnreachable`) | true | Infer Off from repeated host timeouts; connection refusal does not establish Off. |
| Debug logging (`debugLogging`) | false | Additional diagnostic logging; review/redact reports before sharing. |

If an address changes, allow automatic rediscovery or update an intentional
override. See [IP address changed](troubleshooting.md#ip-address-changed).
