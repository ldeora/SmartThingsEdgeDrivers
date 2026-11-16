# Experimental Windows Service installer. Run from elevated PowerShell on an isolated test PC.
# Power is strictly opt-in. Never changes sleep/fast-startup/WOL settings or firmware.
[CmdletBinding(SupportsShouldProcess=$true)]
param(
  [string]$PublishedDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'publish/win-x64'),
  [switch]$SkipFirewall,
  [switch]$EnablePower,
  [string]$HubIPv4 = ''
)
$ErrorActionPreference = 'Stop'
$service = 'ComputerHostAgent'
$programs = Join-Path $env:ProgramFiles 'Computer Host Agent'
$state = Join-Path $env:ProgramData 'ComputerHostAgent'
$exe = Join-Path $programs 'ComputerHost.WindowsAgent.exe'
$source = Join-Path $PublishedDirectory 'ComputerHost.WindowsAgent.exe'
if ($HubIPv4) {
  $addr = $null
  if (-not [Net.IPAddress]::TryParse($HubIPv4, [ref]$addr) -or
      $addr.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
      $addr.Equals([Net.IPAddress]::Any) -or $addr.Equals([Net.IPAddress]::Broadcast) -or
      $addr.GetAddressBytes()[0] -ge 224) {
    throw 'HubIPv4 must be a valid unicast IPv4 address.'
  }
}
if (-not (Test-Path -LiteralPath $source)) { throw "Published executable not found: $source" }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run PowerShell as Administrator.' }
if ($PSCmdlet.ShouldProcess($service, ('Install service; power enabled: ' + [bool]$EnablePower))) {
  # Persisted UUID/boot state intentionally remains in ProgramData between upgrades.
  New-Item -ItemType Directory -Path $state -Force | Out-Null
  $acl = New-Object System.Security.AccessControl.DirectorySecurity
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($sid in @('S-1-5-18','S-1-5-32-544','S-1-5-19')) {
    $identity = [Security.Principal.SecurityIdentifier]::new($sid)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new(
      $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
  }
  Set-Acl -LiteralPath $state -AclObject $acl

  $existing = Get-Service -Name $service -ErrorAction SilentlyContinue
  if ($existing) {
    $installedService = Get-CimInstance Win32_Service -Filter "Name='$service'"
    if ($installedService.StartName -ne 'NT AUTHORITY\LocalService' -or
        $installedService.PathName -notlike '*ComputerHost.WindowsAgent.exe*') {
      throw 'Existing service has unexpected binary/account; refusing to replace it.'
    }
    if ($existing.Status -ne 'Stopped') { Stop-Service -Name $service -ErrorAction Stop }
  }
  New-Item -ItemType Directory -Path $programs -Force | Out-Null
  Copy-Item -Path (Join-Path $PublishedDirectory '*') -Destination $programs -Force -ErrorAction Stop
  # A service upgrade never enables power by accident. -EnablePower must be explicit.
  $configPath = Join-Path $programs 'appsettings.json'
  if (-not (Test-Path -LiteralPath $configPath)) { throw "Missing $configPath" }
  $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
  $config.HostAgent | Add-Member -NotePropertyName EnablePowerControl -NotePropertyValue ([bool]$EnablePower) -Force
  $config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding utf8
  if ($EnablePower) {
    $tokenPath = Join-Path $state 'control-token'
    if (-not (Test-Path -LiteralPath $tokenPath)) {
      # Compatible with Windows PowerShell 5.1 (.NET Framework) and PowerShell 7+.
      $keyBytes = New-Object byte[] 32
      $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
      try { $rng.GetBytes($keyBytes) } finally { $rng.Dispose() }
      $keyHex = ([BitConverter]::ToString($keyBytes)).Replace('-', '').ToLowerInvariant()
      [System.IO.File]::WriteAllText($tokenPath, $keyHex + "`n", [System.Text.Encoding]::ASCII)
    } else {
      $existingKey = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
      if ($existingKey -cnotmatch '^[a-fA-F0-9]{64}$') { throw 'Existing control-token invalid; refusing to rotate automatically.' }
    }
  }
  if (-not $existing) {
    # sc.exe requires the unusual spaces after its "name=" arguments.
    $binPath = '"' + $exe + '"'
    & sc.exe create $service 'binPath=' $binPath 'start=' 'auto' 'obj=' 'NT AUTHORITY\LocalService' 'DisplayName=' 'Computer Host Agent (monitoring)' | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Unable to register ComputerHostAgent Windows Service' }
    & sc.exe failure $service 'reset=' '3600' 'actions=' 'restart/5000/restart/10000/none/0' | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Unable to set service recovery' }
  }
  if (-not $SkipFirewall) {
    Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    $remoteScope = if ($HubIPv4) { $HubIPv4 } else { 'LocalSubnet' }
    New-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -DisplayName 'Computer Host Agent (trusted LAN)' `
      -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Program $exe -Profile Private `
      -RemoteAddress $remoteScope | Out-Null
    Write-Warning "Firewall allows TCP 8765 only from $remoteScope on PRIVATE networks. UDP/5353 mDNS remains subject to Windows network discovery policy."
  }
  Start-Service -Name $service
  Get-Service -Name $service | Format-Table Name,Status,StartType
  Write-Host "Identity/state kept in $state. Power commands enabled: $([bool]$EnablePower)"
  if ($EnablePower) { Write-Warning 'Privileged commands are enabled. Keep control-token secret; put it in SmartThings device preferences only over a trusted channel. Never share it in logs.' }
  Write-Warning 'Unsigned development build: use only on a test PC and do not distribute as a trusted public installer.'
}
