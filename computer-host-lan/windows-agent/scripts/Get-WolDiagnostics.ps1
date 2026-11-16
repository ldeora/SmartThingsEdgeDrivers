# Read-only WOL and power-state diagnostic. Does not change Windows settings.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'
Write-Host '=== Windows power states ==='
powercfg /a
Write-Host '=== Wake-armed devices ==='
powercfg /devicequery wake_armed
Write-Host '=== Network adapters ==='
Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,MacAddress,LinkSpeed | Format-Table
Write-Host '=== Adapter power management ==='
Get-NetAdapterPowerManagement -ErrorAction Continue | Format-Table
Write-Warning 'These are configuration hints, NOT proof of wake from sleep, hibernate, Fast Startup, or S5. Test Wake only when physical recovery is possible.'
