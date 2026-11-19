# Read-only diagnostics: avoids tokens, UUIDs, raw IP/MACs and hostnames.
# Review the generated JSON before attaching it to a PUBLIC GitHub issue.
[CmdletBinding()]
param([string]$OutputPath = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'ComputerHost-Diagnostics.json'))
$ErrorActionPreference = 'Stop'
function Try-Collect([scriptblock]$Script) {
  try { & $Script }
  catch { [ordered]@{ available = $false; error_type = $_.Exception.GetType().Name } }
}
# Read the installed listener port without disclosing the saved hub address.
# Diagnostics should keep working when appsettings.json uses a nondefault port.
$agentPort = 8765
try {
  $configFile = Join-Path $env:ProgramFiles 'Computer Host Agent/appsettings.json'
  if (Test-Path -LiteralPath $configFile) {
    $config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
    $candidate = 0
    if ([int]::TryParse([string]$config.HostAgent.Port, [ref]$candidate) -and
        $candidate -ge 1024 -and $candidate -le 65535) {
      $agentPort = $candidate
    }
  }
} catch { }
$agentBase = "http://127.0.0.1:$agentPort"
$report = [ordered]@{
  report_format = 'computer-host-diagnostics-v1'
  collected_utc = (Get-Date).ToUniversalTime().ToString('o')
  notice = 'No token, UUID, hostname, IP, MAC or raw event logs collected; review before sharing.'
  os = Try-Collect {
    $o = Get-CimInstance Win32_OperatingSystem
    [ordered]@{ caption=$o.Caption; version=$o.Version; build=$o.BuildNumber; architecture=$o.OSArchitecture }
  }
  power_states = Try-Collect { @(powercfg /a) }
  wake_armed_device_count = Try-Collect { @((powercfg /devicequery wake_armed) | Where-Object { $_.Trim() }).Count }
  service = Try-Collect {
    $s = Get-CimInstance Win32_Service -Filter "Name='ComputerHostAgent'"
    if (-not $s) { return [ordered]@{ installed=$false } }
    [ordered]@{ installed=$true; state=$s.State; start_mode=$s.StartMode; account=$s.StartName }
  }
  state_acl = Try-Collect {
    $p = Join-Path $env:ProgramData 'ComputerHostAgent'
    if (-not (Test-Path -LiteralPath $p)) { return [ordered]@{ present=$false } }
    $acl = Get-Acl -LiteralPath $p
    [ordered]@{ present=$true; inheritance_disabled=$acl.AreAccessRulesProtected;
      allowed_sids=@($acl.Access | Where-Object AccessControlType -eq 'Allow' |
        ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } | Sort-Object -Unique) }
  }
  firewall = Try-Collect {
    $r = Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction SilentlyContinue
    if (-not $r) { return [ordered]@{ present=$false } }
    $f = $r | Get-NetFirewallAddressFilter
    [ordered]@{ present=$true; enabled=$r.Enabled.ToString(); profile=$r.Profile.ToString();
      scope_is_local_subnet=(@($f.RemoteAddress) -contains 'LocalSubnet');
      scope_is_single_address=(@($f.RemoteAddress) | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' }).Count -eq 1 }
  }
  agent_info = Try-Collect {
    $v = Invoke-RestMethod "$agentBase/v2/info" -TimeoutSec 3
    [ordered]@{ reachable=$true; protocol=$v.protocol; api_version=$v.api_version;
      agent_version=$v.agent_version; platform=$v.platform; features=$v.features;
      power_actions=$v.power_actions; wol_mac_present=($null -ne $v.wol_mac);
      wol_broadcast_present=($null -ne $v.wol_broadcast) }
  }
  agent_health = Try-Collect {
    $v = Invoke-RestMethod "$agentBase/v2/health" -TimeoutSec 3
    [ordered]@{ status=$v.status; uptime_seconds=$v.uptime_seconds }
  }
  agent_metrics = Try-Collect {
    $v = Invoke-RestMethod "$agentBase/v2/metrics" -TimeoutSec 3
    [ordered]@{ cpu_usage_percent=$v.cpu_usage_percent; memory_usage_percent=$v.memory_usage_percent;
      memory_total_bytes=$v.memory_total_bytes; disk_root_usage_percent=$v.disk_root_usage_percent }
  }
}
$dir = Split-Path -Parent $OutputPath
if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Sanitized diagnostic report written to: $OutputPath"
Write-Warning 'Review before sharing. This utility does not capture network packets, local host IDs or raw event logs.'
