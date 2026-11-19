# Recover a pre-upgrade Windows agent after a failed graphical installation.
# The snapshot is admin-protected in Program Files; persistent keys/UUIDs are
# never copied, logged, or deleted. A successful upgrade commits the snapshot.
[CmdletBinding()]
param([ValidateSet('Restore','Commit')][string]$Mode = 'Restore')
$ErrorActionPreference = 'Stop'
$programRoot = if ([Environment]::Is64BitOperatingSystem -and $env:ProgramW6432) {
  $env:ProgramW6432
} else { $env:ProgramFiles }
$programs = Join-Path $programRoot 'Computer Host Agent'
$backup = $programs + '.upgrade-rollback'
if (-not (Test-Path -LiteralPath $backup -PathType Container)) { return }
$service = 'ComputerHostAgent'
$exe = Join-Path $programs 'ComputerHost.WindowsAgent.exe'
$svc = Get-CimInstance Win32_Service -Filter "Name='$service'" -ErrorAction Stop
if (-not $svc -or $svc.StartName -ne 'NT AUTHORITY\LocalService' -or
    -not [string]::Equals($svc.PathName.Trim().Trim('"'), $exe,
      [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Upgrade recovery refused: service account or executable path differs.'
}
if ($Mode -eq 'Commit') {
  Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
  return
}
if (-not (Test-Path -LiteralPath (Join-Path $backup 'ComputerHost.WindowsAgent.exe') -PathType Leaf)) {
  throw 'Original agent binary missing from upgrade snapshot.'
}
$running = Get-Service -Name $service -ErrorAction Stop
if ($running.Status -ne 'Stopped') {
  Stop-Service -Name $service -ErrorAction Stop
  (Get-Service -Name $service).WaitForStatus(
    [System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(40))
}
# Copy original agent/configuration back; avoid deleting unrelated files in
# the Inno-managed application directory.
Get-ChildItem -LiteralPath $backup -Force | Where-Object {
  $_.Name -ne 'firewall-rollback.json'
} | Copy-Item -Destination $programs -Recurse -Force -ErrorAction Stop
$firewallSnapshot = Join-Path $backup 'firewall-rollback.json'
if (Test-Path -LiteralPath $firewallSnapshot) {
  $saved = Get-Content -LiteralPath $firewallSnapshot -Raw | ConvertFrom-Json
  Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction Stop
  if ($saved.Present) {
    New-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -DisplayName 'Computer Host Agent (trusted LAN)' `
      -Direction Inbound -Action Allow -Protocol TCP -LocalPort @($saved.LocalPort) `
      -Program $exe -Profile $saved.Profile -RemoteAddress @($saved.RemoteAddress) | Out-Null
  }
}
Start-Service -Name $service -ErrorAction Stop
(Get-Service -Name $service).WaitForStatus(
  [System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))
Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
Write-Host 'Previous Computer Host Agent files, firewall and service restored.'
