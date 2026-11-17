# Computer Host LAN OPTIONAL proof of concept. Never called by the installed agent.
# Intended to run as the currently logged-on desktop user, not from Session 0.
# Without -Execute it only checks prerequisites; it will not lock the computer.
[CmdletBinding()]
param([switch]$Execute)
$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Windows is required.'
}

$sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($sessionId -le 0 -or -not [Environment]::UserInteractive) {
    throw "Interactive desktop required. Current session=$sessionId, user=$user. Service/Session 0 cannot lock a desktop."
}

if (-not $Execute) {
    Write-Host "PASS: running under $user in interactive session $sessionId. No lock was requested."
    exit 0
}

# Use the documented Win32 API rather than rundll32.exe (which expects a
# different DLL entry-point signature).
if (-not ('ComputerHost.LockProofOfConcept.Native' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace ComputerHost.LockProofOfConcept {
    public static class Native {
        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool LockWorkStation();
    }
}
'@ -ErrorAction Stop
}

if (-not [ComputerHost.LockProofOfConcept.Native]::LockWorkStation()) {
    $win32 = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw "Windows did not initiate the lock (Win32 error $win32). It may already be locked or on a non-interactive desktop."
}
# Windows reports initiation, not completion. No session status is claimed.
Write-Host "Lock requested for interactive session $sessionId (completion not verified)."
