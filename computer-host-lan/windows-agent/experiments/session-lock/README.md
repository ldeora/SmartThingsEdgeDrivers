# Windows workstation locking — separate, manual proof of concept

**Status:** Research/PoC ONLY. Not part of the Computer Host LAN agent, the Edge Driver, installer, published beta, SmartThings channel or release package. **Do not merge into the release path yet.**

## Why this is separate

`ComputerHostAgent` currently runs as `NT AUTHORITY\LocalService` in Windows Session 0. Microsoft's `LockWorkStation()` API only works from an **interactive desktop session** where a user is logged on. Executing it directly from the Windows Service would be incorrect, even if the API call returned success.

A per-user Scheduled Task with `InteractiveToken` can run a tiny one-shot action within the user's existing session without storing credentials or requiring a permanently running tray application. This PoC tests **only that user-side mechanism**, not remote SmartThings control.

**Important revised feasibility finding:** Even when a task has suitable file DACL entries, `LocalService` is not automatically allowed to run it on behalf of another user. Task Scheduler `RunEx`/RPC documentation applies additional caller/owner/session restrictions (see `SchRpcRun`). Granting access to the task alone is therefore **not** proof that the service can launch a user-session task. This remains an explicit blocker until tested and reviewed; do **not** switch the main service to LocalSystem, grant service interactive-token privileges or weaken ACLs.

## Test on a Windows 11 test PC

These scripts require Windows PowerShell 5.1 with the built-in ScheduledTasks module. Test with a user **actually signed in at the Windows desktop**, not through the existing Windows service, an elevated SYSTEM shell or an unattended CI runner.

From a normal (non-elevated) interactive PowerShell window in this folder:

```powershell
# Inspect prerequisites, without locking
.\Invoke-LocalSessionLock.ps1
# Read-only task status
.\Test-InteractiveLockTask.ps1

# Manually register one on-demand, non-elevated task for this logged-in user
.\Test-InteractiveLockTask.ps1 -Install -WhatIf
.\Test-InteractiveLockTask.ps1 -Install

# WARNING: the following WILL request workstation locking; save your work
.\Test-InteractiveLockTask.ps1 -Run

# Remove the on-demand test task when finished
.\Test-InteractiveLockTask.ps1 -Remove
```

No trigger is registered: the scheduled task cannot lock spontaneously. No credentials, network listener, new Windows Service, startup program, power settings, firewall rules or SmartThings devices are modified. `-WhatIf` is supported for the mutating commands. The script refuses to replace any existing task with the same name.

`Invoke-LocalSessionLock.ps1` can be called directly with `-Execute` to distinguish whether the locking API itself works in an ordinary user session, but `-Run` is the preferred scheduler-path test.

The task runs **as the current user**, in the current user session, at **Limited** privilege. On a shared/RDP computer, the task may not correspond to the intended console session; this PoC is intended for one logged-in user on a simple physical test PC. If no user is logged in, no interactive task should run.

A successful Task Scheduler start or a nonzero `LockWorkStation()` return means the **request was initiated**, not that the workstation is confirmed locked. Verify the actual lock screen manually.

## Evidence to record

1. Windows build, PowerShell version, account type (local/domain, not username), physical console vs RDP.
2. User-session check prints a session ID greater than zero.
3. The task registers without requiring a password or elevation.
4. `-Run` locks the visible session on a single-user PC and the user can unlock it normally.
5. Running `-Remove` removes the registered task; no changes to the Computer Host Agent or its device.
6. If task registration fails as a standard user, record the error; do not bypass policy by running as SYSTEM.
7. Record whether other sessions, already-locked sessions or no-logon cases are relevant. Do not claim they are supported without hardware tests.

## Before any real SmartThings integration

- Determine a **permitted and bounded invocation path from LocalService to the interactive user** without elevating the service or making an arbitrary process launcher. Task Scheduler's cross-account restrictions must be respected. Merely invoking `schtasks /run` as LocalService is not assumed to work.
- Verify task identity, action integrity, task/command path ownership, DACL and impersonation boundaries. This PoC's task action references a developer checkout path, which is acceptable for a **same-user, non-elevated manual test only**. Never deploy a LocalService-triggered task pointing at a user-writable path.
- Select the intended session deterministically; handle no user, already locked, simultaneous RDP sessions and policy denials.
- Require opt-in and use the existing HMAC challenge protocol without changing the semantics of `shutdown`, `reboot` or `suspend`. If `lock` is ever implemented, it must leave the SmartThings power switch **ON**, must advertise capability only when available, and must not be mistaken for power-off.
- If these requirements demand a larger persistent helper/broker, postpone this feature until **after** the stable release rather than destabilizing Computer Host LAN.

## Official references

- LockWorkStation: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-lockworkstation
- Task Scheduler interactive token: https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype
- Task access control: https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks
- RegisteredTask.RunEx session behavior: https://learn.microsoft.com/en-us/windows/win32/taskschd/registeredtask-runex
- Task Scheduler service-side RPC restrictions: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-tsch/77f2250d-500a-40ee-be18-c82f7079c4f0
