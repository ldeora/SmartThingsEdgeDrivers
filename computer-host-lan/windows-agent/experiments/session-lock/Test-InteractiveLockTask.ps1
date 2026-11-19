# OPTIONAL Windows-only research script. Nothing is changed by invoking without a switch.
# This task is limited to the current logged-in user and has NO triggers.
# It is NOT accessible from the installed Computer Host Windows Service.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Install,
    [switch]$Run,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows is required.'
}
$selected = @($Install.IsPresent, $Run.IsPresent, $Remove.IsPresent) | Where-Object { $_ }
if (@($selected).Count -gt 1) { throw 'Choose only one of -Install, -Run or -Remove.' }

$taskName = 'ComputerHost-InteractiveLock-POC'
$lockScript = Join-Path $PSScriptRoot 'Invoke-LocalSessionLock.ps1'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$user = $identity.Name
$session = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
if ($session -le 0) {
    throw 'Run from a logged-on Windows user session, not as a service in Session 0.'
}

Import-Module ScheduledTasks -ErrorAction Stop
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if (-not ($Install -or $Run -or $Remove)) {
    Write-Host "Interactive Task Scheduler experiment for $user (session $session)."
    Write-Host "Task: $taskName; installed: $([bool]$existing)"
    Write-Host 'Use -Install to register a per-user task; -Run to request a lock; -Remove to unregister.'
    return
}

if ($Install) {
    if ($existing) { throw "Task '$taskName' already exists. Refusing to overwrite it." }
    if (-not (Test-Path -LiteralPath $lockScript)) { throw "Missing $lockScript" }
    if ($lockScript.Contains('"')) { throw 'Unexpected quote character in script path.' }

    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = '-NoLogo -NoProfile -WindowStyle Hidden -File "' + $lockScript + '" -Execute'
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    # Interactive token: never save a password, never elevate the user's task.
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
    $definition = New-ScheduledTask -Action $action -Principal $principal -Settings $settings
    if ($PSCmdlet.ShouldProcess($taskName, "Register on-demand, limited-user interactive task for $user")) {
        Register-ScheduledTask -TaskName $taskName -InputObject $definition -ErrorAction Stop | Out-Null
        Write-Host "Registered $taskName for $user. NO trigger was installed and nothing was locked."
    }
} elseif ($Run) {
    if (-not $existing) { throw "Task '$taskName' not installed. Run -Install first." }
    if (@($existing.Actions).Count -ne 1 -or $existing.Actions[0].Arguments -notlike '*Invoke-LocalSessionLock.ps1*') {
        throw 'Existing task does not match our proof of concept; refusing to run it.'
    }
    if ($PSCmdlet.ShouldProcess($taskName, 'Run task now and request Windows workstation lock')) {
        Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        Write-Host 'Task execution requested. Verify manually whether Windows locked; this does not confirm completion.'
    }
} elseif ($Remove) {
    if (-not $existing) {
        Write-Host "Task '$taskName' was not present."
        return
    }
    if (@($existing.Actions).Count -ne 1 -or $existing.Actions[0].Arguments -notlike '*Invoke-LocalSessionLock.ps1*') {
        throw 'Existing task does not match our proof of concept; refusing to remove it.'
    }
    if ($PSCmdlet.ShouldProcess($taskName, 'Unregister proof-of-concept task')) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
        Write-Host "Unregistered $taskName."
    }
}
