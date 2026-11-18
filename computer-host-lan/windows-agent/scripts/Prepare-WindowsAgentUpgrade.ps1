# Used by the graphical installer BEFORE Inno replaces files.
# Avoid modifying an unrelated service that happens to use our service name.
[CmdletBinding()]
param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$serviceName = 'ComputerHostAgent'
$service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction Stop
if (-not $service) { return }
$installedPath = Join-Path (Join-Path $env:ProgramFiles 'Computer Host Agent') 'ComputerHost.WindowsAgent.exe'
if ($service.StartName -ne 'NT AUTHORITY\LocalService') {
    throw 'Existing service is not owned by the expected LocalService account; refusing to replace.'
}
# Normalize quotes without accepting a differently located executable.
$path = $service.PathName.Trim().Trim('"')
if (-not [string]::Equals($path, $installedPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Existing service executable path does not match Computer Host Agent; refusing to replace.'
}
if ($ValidateOnly) { Write-Host 'PASS existing agent service ownership validation'; return }
$running = Get-Service -Name $serviceName -ErrorAction Stop
if ($running.Status -ne 'Stopped') {
    Stop-Service -Name $serviceName -ErrorAction Stop
    (Get-Service -Name $serviceName).WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Stopped,
        [TimeSpan]::FromSeconds(40))
}
