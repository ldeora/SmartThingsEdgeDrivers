# Change only the Computer Host Agent firewall allow-list when a hub moves IP.
# Run in elevated Windows PowerShell. Does not change the service, config or power consent.
[CmdletBinding(SupportsShouldProcess=$true)]
param([Parameter(Mandatory)][string]$HubIPv4)
$ErrorActionPreference = 'Stop'
$ip = $null
if (-not [Net.IPAddress]::TryParse($HubIPv4, [ref]$ip) -or
    $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $ip.ToString() -cne $HubIPv4 -or $ip.GetAddressBytes()[0] -eq 0 -or
    $ip.GetAddressBytes()[0] -eq 127 -or $ip.GetAddressBytes()[0] -ge 224 -or
    ($ip.GetAddressBytes()[0] -eq 169 -and $ip.GetAddressBytes()[1] -eq 254)) {
  throw 'HubIPv4 must be a canonical unicast IPv4 address.'
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator privileges required.' }
$rule = Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction Stop
if ($rule.Direction -ne 'Inbound' -or $rule.Action -ne 'Allow' -or
    $rule.Profile.ToString() -ne 'Private') { throw 'Unexpected firewall rule; refusing to modify it.' }
if ($PSCmdlet.ShouldProcess('ComputerHostAgent firewall rule', 'Allow the new hub IPv4 only')) {
  $rule | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $HubIPv4 -ErrorAction Stop | Out-Null
  Write-Host 'Hub firewall scope updated. Keep the hub address stable using a DHCP reservation.'
}
