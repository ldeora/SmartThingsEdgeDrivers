# Stop and delete only the ComputerHostAgent service. Preserve state unless explicitly purged.
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$PurgeState, [switch]$KeepProgramFiles)
$ErrorActionPreference = 'Stop'
$service = 'ComputerHostAgent'
# Inno Setup invokes Windows PowerShell from a 32-bit bootstrapper on some
# systems. ProgramFiles in that process may mean Program Files (x86).
# ProgramW6432 always identifies the 64-bit installation root on x64.
$programRoot = if ([Environment]::Is64BitOperatingSystem -and $env:ProgramW6432) {
  $env:ProgramW6432
} else {
  $env:ProgramFiles
}
$programs = Join-Path $programRoot 'Computer Host Agent'
$state = Join-Path $env:ProgramData 'ComputerHostAgent'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run PowerShell as Administrator.' }
if ($PSCmdlet.ShouldProcess($service, 'Stop and remove Computer Host Agent service')) {
  $existing = Get-Service -Name $service -ErrorAction SilentlyContinue
  if ($existing) {
    if ($existing.Status -ne 'Stopped') { Stop-Service -Name $service -ErrorAction Stop }
    & sc.exe delete $service | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'sc.exe delete failed' }
  }
  Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  if (-not $KeepProgramFiles -and (Test-Path -LiteralPath $programs)) {
    Remove-Item -LiteralPath $programs -Recurse -Force
  }
  if ($PurgeState -and (Test-Path -LiteralPath $state)) { Remove-Item -LiteralPath $state -Recurse -Force }
  Write-Host ('Removed service and executable. Persistent identity ' + $(if ($PurgeState) { 'purged' } else { 'preserved' }))
}
