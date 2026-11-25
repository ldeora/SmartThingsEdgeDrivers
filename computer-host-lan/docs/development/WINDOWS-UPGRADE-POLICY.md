# Windows upgrade policy (#126 / #127)

Approved scope from #170; post-rc.2 development for rc.3. No change to
persistent identity, token ACL policy, service ownership or protocol.
An installed service is an upgrade; retained state without a registered
service is a reinstall and requires a new explicit network choice. Existing
valid identity and token are retained in either case.

| Path | Fresh / reinstall | Upgrade: no explicit changes | Explicit power change | Explicit scope change | Missing / ambiguous previous scope |
| --- | --- | --- | --- | --- | --- |
| Setup GUI | Default off; choose hub or explicitly opt in to Private LocalSubnet | Prefill prior validated scope and power choice; no initial rediscovery | Checkbox on/off | Select or enter hub, or explicitly select LocalSubnet | Require user selection; no automatic broader scope |
| Setup silent | Default off; require /HUBIP or /LOCALSUBNET=1 | Retain power and validated scope | /ENABLEPOWER=1 or 0 | /HUBIP or /LOCALSUBNET=1 | Refuse before stopping service unless explicit valid replacement |
| ZIP/PowerShell | Default off; require -HubIPv4 or -LocalSubnet | Retain power and validated scope | -EnablePower or -DisablePower | -HubIPv4 or -LocalSubnet | Refuse before mutation unless explicit valid replacement |

Conflicting power or scope choices and invalid explicit values refuse.
Existing power setting must be a JSON boolean; an unreadable or malformed
existing configuration is not interpreted as an opt-in. A missing legacy
power property means off. Preserve unrelated custom settings. Prior firewall
scope must be exactly one enabled Private inbound TCP allow rule for this
agent executable with one canonical unicast IPv4 or LocalSubnet; do not
reuse arbitrary address lists, ranges, Any, Public or unrelated rules.
Recreate only the project's named rule using the selected scope and current
configured port. Explicit -SkipFirewall is a test/advanced escape that
does not change firewall rules; it is not a wizard fallback.

Acceptance: exercise fresh off, implicit upgrade keep on/off, explicit
enable/disable, hub scope keep/change, LocalSubnet keep/change, missing or
ambiguous scope refusal, conflicting flags, config and UUID/key retention.
Verify actual installed service and firewall, not just command construction.
Use only disposable CI state; never send authenticated power commands.
GUI prefill requires native desktop verification; silent/ZIP cases can
be covered by the existing native install workflows. Physical rc.3
acceptance remains required.
