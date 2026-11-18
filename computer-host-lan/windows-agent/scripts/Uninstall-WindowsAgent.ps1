# Stop and delete only the ComputerHostAgent service. Preserve state unless explicitly purged.
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$PurgeState, [switch]$KeepProgramFiles)
$ErrorActionPreference = 'Stop'
$service = 'ComputerHostAgent'
$programs = Join-Path $env:ProgramFiles 'Computer Host Agent'
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
