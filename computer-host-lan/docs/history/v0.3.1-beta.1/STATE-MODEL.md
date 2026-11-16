# Linux Host logical state model — 0.2.9

The Edge Driver monitors a remote Linux agent over HTTP. It is **not an ACPI
power-state sensor**. A silent host is compatible with shutdown, suspend,
a network outage, firewall changes, unplugged cable or hub communication loss.

| Observation | Host status | Main Switch behavior | Evidence |
|---|---|---|---|
| Matching agent health reply | `running` | ON | Confirmed agent / UUID |
| WOL sent, awaiting reply | `starting` | Preserve prior state | Requested, not confirmed |
| Signed shutdown acknowledged | `stopping` | ON until inferred completion | Request accepted |
| Shutdown + repeated silent timeouts | `stopped` | OFF | Inferred completion |
| Signed suspend acknowledged | `suspending` | ON until inferred completion | Request accepted |
| Suspend + repeated silent timeouts | `suspended` | OFF | Inferred completion |
| Reboot accepted, same boot ID | `rebooting` | ON | Not yet confirmed |
| Matching health with changed boot ID | `running` | ON | Confirmed new boot |
| Agent connection refused, no power action | `unreachable` | ON | TCP/IP stack responded |
| Timeouts, no power action | `unreachable` | OFF if preference enabled; else unchanged | Ambiguous network loss |
| Wrong installation UUID / other unknown failure | `unknown` | Unchanged | No power inference |

`failureThreshold` controls consecutive failed health polls (default 3).
The host-timeout counter resets when an `agent_unavailable` / other error occurs,
so stale timeouts cannot confirm a shutdown. An acknowledged action expires
after 180 seconds if the expected event is not observed; the driver then
returns to regular state evaluation and logs the incomplete transition.

For a public beta, the default `assumeOffWhenUnreachable=true` preserves the
user-tested convenient switch behavior. Users on flaky networks can turn this
off to avoid spuriously reporting Off. The separate `linuxHostStatus`
capability always distinguishes `unreachable` from action-inferred `stopped`.

No attempt is made to infer wake support from the agent being online. WOL
magic packets are sent from the hub to the MAC previously verified by the
agent (or configured manually). WOL enablement/persistence remains host-side.
