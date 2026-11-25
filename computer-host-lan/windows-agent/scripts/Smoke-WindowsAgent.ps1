# CI smoke test for the built native monitoring agent; deliberately disables mDNS in CI.
[CmdletBinding()]
param([string]$Executable)
$ErrorActionPreference = 'Stop'
if (-not $Executable) { throw 'Pass -Executable <full path to published exe>' }
if (-not (Test-Path -LiteralPath $Executable)) { throw "Executable not found: $Executable" }
$state = Join-Path $env:TEMP "computerhost-smoke-$([Guid]::NewGuid().ToString('N'))"
$env:HostAgent__StateDirectory = $state
$env:HostAgent__Port = '18765'
$env:HostAgent__DiscoveryEnabled = 'false'
$base = 'http://127.0.0.1:18765'
# Test-fixture comparison: ignore Windows' automatic SDDL control flags,
# but retain protection and every explicit/inherited allow/deny rule.
function Get-AccessRuleSnapshot($security) {
  $rules = @($security.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) |
    ForEach-Object {
      '{0}:{1}:{2}:{3}:{4}:{5}' -f $_.IdentityReference.Value, $_.AccessControlType,
        ([int]$_.FileSystemRights), $_.InheritanceFlags, $_.PropagationFlags, $_.IsInherited
    })
  [string[]]$sorted = $rules
  [Array]::Sort($sorted, [StringComparer]::Ordinal)
  $protection = if ($security.AreAccessRulesProtected) { 'P|' } else { '|' }
  return ($protection + ($sorted -join ';'))
}
function Start-Agent {
  $p = Start-Process -FilePath $Executable -PassThru -WindowStyle Hidden
  for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 300
    if ($p.HasExited) { throw "Agent exited during startup: $($p.ExitCode)" }
    try {
      $info = Invoke-RestMethod -Uri "$base/v2/info" -TimeoutSec 2
      if ($info.protocol -eq 'computer-host-agent') { return $p }
    } catch { }
  }
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  throw 'Agent did not become reachable on TCP 18765'
}
function Stop-Agent($p) {
  if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction Stop }
  $p.WaitForExit(4000) | Out-Null
}
try {
  # Console smoke uses an explicitly selected, private, pre-provisioned
  # test directory. Installed LocalService uses the installer-owned policy.
  $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
  $acl = New-Object Security.AccessControl.DirectorySecurity
  $acl.SetOwner($owner)
  $acl.SetAccessRuleProtection($true, $false)
  $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $owner, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
  if ($PSVersionTable.PSVersion.Major -le 5) {
    [void][IO.Directory]::CreateDirectory($state, $acl)
  } else {
    [IO.FileSystemAclExtensions]::Create([IO.DirectoryInfo]::new($state), $acl)
  }
  $p = Start-Agent
  try {
    $info = Invoke-RestMethod -Uri "$base/v2/info" -TimeoutSec 3
    $health = Invoke-RestMethod -Uri "$base/v2/health" -TimeoutSec 3
    $metrics = Invoke-RestMethod -Uri "$base/v2/metrics" -TimeoutSec 3
    if ($info.platform -ne 'windows' -or $info.api_version -ne 2) { throw 'Incorrect info envelope' }
    $release = Get-Content -LiteralPath (Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'release.json') -Raw | ConvertFrom-Json
    if ($info.agent_version -ne $release.windows_agent) { throw 'Runtime agent version differs from release.json' }
    if ($health.id -ne $info.id -or $metrics.id -ne $info.id) { throw 'Identity mismatch' }
    if ($info.power_actions.Count -ne 0) { throw 'Power enabled without opt-in' }
    if ($health.status -ne 'running' -or $health.uptime_seconds -le 0) { throw 'Health invalid' }
    if ($metrics.memory_total_bytes -lt 1 -or $metrics.disk_root_usage_percent -lt 0) { throw 'Metrics invalid' }
    if ($null -ne $metrics.cpu_temperature_c) { throw 'Unverified CPU temp was fabricated' }
    try { Invoke-WebRequest -Uri "$base/v2/challenge" -TimeoutSec 3 -ErrorAction Stop | Out-Null; throw 'Challenge unexpectedly allowed' }
    catch { if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw } }
    try { Invoke-WebRequest -Uri "$base/v2/power/shutdown" -Method Post -TimeoutSec 3 -ErrorAction Stop | Out-Null; throw 'Power unexpectedly allowed' }
    catch { if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw } }
    $oldId, $oldBoot = $info.id, $health.boot_id
  }
  finally { Stop-Agent $p }
  $p = Start-Agent
  try {
    $info = Invoke-RestMethod -Uri "$base/v2/info" -TimeoutSec 3
    $health = Invoke-RestMethod -Uri "$base/v2/health" -TimeoutSec 3
    if ($info.id -ne $oldId) { throw 'UUID changed after agent restart' }
    if ($health.boot_id -ne $oldBoot) { throw 'Boot ID changed after service restart' }
    Write-Host 'PASS monitoring-only HTTP endpoints, UUID and boot-ID persistence'
  }
  finally { Stop-Agent $p }
  # Enabled-mode smoke never sends a valid authenticated power request.
  $keyBytes = New-Object byte[] 32
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($keyBytes) } finally { $rng.Dispose() }
  $keyPath = Join-Path $state 'control-token'
  $env:HostAgent__EnablePowerControl = 'true'
  function Assert-MonitoringWithoutPower {
    $process = Start-Agent
    try {
      $info = Invoke-RestMethod -Uri "$base/v2/info" -TimeoutSec 3
      $health = Invoke-RestMethod -Uri "$base/v2/health" -TimeoutSec 3
      $metrics = Invoke-RestMethod -Uri "$base/v2/metrics" -TimeoutSec 3
      if ($info.id -ne $oldId -or $health.id -ne $oldId -or $metrics.id -ne $oldId -or
          @($info.power_actions).Count -ne 0) { throw 'Degraded power changed identity or monitoring' }
      try { Invoke-WebRequest -Uri "$base/v2/challenge" -TimeoutSec 3 -ErrorAction Stop | Out-Null; throw 'Challenge unexpectedly allowed' }
      catch { if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw } }
      try { Invoke-WebRequest -Uri "$base/v2/power/shutdown" -Method Post -TimeoutSec 3 -ErrorAction Stop | Out-Null; throw 'Power unexpectedly allowed' }
      catch { if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw } }
    } finally { Stop-Agent $process }
  }
  Assert-MonitoringWithoutPower
  if (Test-Path -LiteralPath $keyPath) { throw 'Missing token was generated' }
  [IO.File]::WriteAllText($keyPath, 'malformed')
  $keyAcl = Get-Acl -LiteralPath $keyPath
  $keyAcl.SetAccessRuleProtection($true, $false)
  $keyAcl.SetOwner($owner)
  $keyAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner, 'FullControl', 'Allow'))
  Set-Acl -LiteralPath $keyPath -AclObject $keyAcl
  Assert-MonitoringWithoutPower
  if ([IO.File]::ReadAllText($keyPath) -ne 'malformed') { throw 'Invalid token changed' }
  [IO.File]::WriteAllText($keyPath, ([BitConverter]::ToString($keyBytes)).Replace('-', '').ToLowerInvariant())
  $unsafeAcl = Get-Acl -LiteralPath $keyPath
  $everyone = [Security.Principal.SecurityIdentifier]::new('S-1-1-0')
  $originalDacl = Get-AccessRuleSnapshot $unsafeAcl
  $injectedRule = [Security.AccessControl.FileSystemAccessRule]::new($everyone, 'Read', 'Allow')
  $unsafeAcl.AddAccessRule($injectedRule)
  Set-Acl -LiteralPath $keyPath -AclObject $unsafeAcl
  try { Assert-MonitoringWithoutPower } finally {
    $unsafeAcl.RemoveAccessRuleSpecific($injectedRule)
    Set-Acl -LiteralPath $keyPath -AclObject $unsafeAcl
    $restoredDacl = Get-AccessRuleSnapshot (Get-Acl -LiteralPath $keyPath)
    if ($restoredDacl -cne $originalDacl) {
      throw "Console smoke did not restore original token DACL.`nExpected: $originalDacl`nObserved: $restoredDacl"
    }
  }
  Write-Host 'PASS missing, malformed and unsafe token leave HTTP monitoring active and power denied'
  $p = Start-Agent
  try {
    $info = Invoke-RestMethod -Uri "$base/v2/info" -TimeoutSec 3
    if (@($info.power_actions).Count -ne 3) { throw 'Power capability not advertised when explicitly enabled' }
    $challenge = Invoke-RestMethod -Uri "$base/v2/challenge" -TimeoutSec 3
    if ($challenge.nonce.Length -ne 48) { throw 'Invalid challenge length' }
    try {
      Invoke-WebRequest -Uri "$base/v2/power/reboot" -Method Post -Headers @{
        'X-ComputerHost-Nonce' = $challenge.nonce
        'X-ComputerHost-Signature' = ('0' * 64)
      } -ContentType 'application/json' -Body '' -TimeoutSec 3 -ErrorAction Stop | Out-Null
      throw 'Invalid HMAC was accepted (unsafe)'
    } catch {
      if ($_.Exception.Response.StatusCode.value__ -ne 401) { throw }
    }
    Write-Host 'PASS opt-in power advertisement, challenge and invalid-HMAC denial (no real power command sent)'
  }
  finally { Stop-Agent $p }
}
finally {
  Remove-Item Env:HostAgent__EnablePowerControl -ErrorAction SilentlyContinue
  Remove-Item Env:HostAgent__StateDirectory -ErrorAction SilentlyContinue
  Remove-Item Env:HostAgent__Port -ErrorAction SilentlyContinue
  Remove-Item Env:HostAgent__DiscoveryEnabled -ErrorAction SilentlyContinue
  if (Test-Path $state) { Remove-Item -Path $state -Recurse -Force }
}
