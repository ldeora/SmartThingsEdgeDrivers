# Volunteer testing checklist

Use only the trusted, version-matched [published release](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.3) and
[SmartThings driver](smartthings.md#add-a-computer). This is a practical
volunteer checklist, not a claim that every test has passed. No special
hardware is needed for monitoring; optional power requires physical access.
Save your work. Do not test unsafe-state or destructive recovery fixtures on
a working computer.

| Check | Expected result |
| --- | --- |
| Fresh install | Monitoring-only default; one new device with correct profile. |
| Windows Setup | Welcome and first hub-search pages display properly at normal scaling; search retry, manual IPv4 and firewall scope are usable. |
| Linux installer | Wizard, review, authorization, result and terminal input work; no unexpected network changes. |
| Upgrade | Same device, settings, key and routines; no uninstall/re-pair; running agent version correct. |
| Telemetry | CPU, RAM/disk percentages and capacities, uptime, supported platform extras and status plausible. |
| Device tile | Host Status and switch action, detail view, settings and routines work. |
| Service recovery | Restarting the service resumes reporting on the same device. |
| Network changes | Rediscovery after host address change; appropriate firewall update after hub address change. |
| Multiple computers | Each reports its own measurements; no duplicates or cross-control. |
| Optional power | Reboot, suspend/wake and shutdown/wake where supported; record observed state separately from command acknowledgement. |
| WOL persistence (Linux) | Supported wired adapter still wakes after reboot; report network manager and unsupported states. |
| Maintenance | Normal repair, reinstall or uninstall if desired; retained identity reuses existing device. Never manufacture interrupted transactions on a real installation. |
| Soak | Leave running during normal use and note missed updates, false state changes or service failures. |

Report PASS / FAIL / NOT TESTED / N/A for each attempted check; unsupported
hardware wake is not automatically an installer failure. Include exact
integration, agent and installed driver versions, OS/build, CPU architecture,
hub model/firmware, Ethernet/Wi-Fi, expected and actual behavior and elapsed
time. Don't share keys, UUIDs, addresses or unreviewed logs.

See [diagnostics and reporting](troubleshooting.md#reporting-a-problem).
