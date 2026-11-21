# Experimental Windows Service installer. Run from elevated PowerShell on an isolated test PC.
# Power is strictly opt-in. Never changes sleep/fast-startup/WOL settings or firmware.
[CmdletBinding(SupportsShouldProcess=$true)]
param(
  [string]$PublishedDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'publish/win-x64'),
  [switch]$SkipFirewall,
  [switch]$EnablePower,
  [switch]$UseExistingFiles,
  [string]$HubIPv4 = '',
  [string]$DiagnosticPath = ''
)
$ErrorActionPreference = 'Stop'
try {
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
  $exe = Join-Path $programs 'ComputerHost.WindowsAgent.exe'
  $source = Join-Path $PublishedDirectory 'ComputerHost.WindowsAgent.exe'
  if ($HubIPv4) {
    $addr = $null
    if (-not [Net.IPAddress]::TryParse($HubIPv4, [ref]$addr) -or
        $addr.ToString() -cne $HubIPv4 -or
        $addr.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        $addr.Equals([Net.IPAddress]::Any) -or $addr.Equals([Net.IPAddress]::Broadcast) -or
        $addr.GetAddressBytes()[0] -ge 224) {
      throw 'HubIPv4 must be a valid unicast IPv4 address.'
    }
  }
  if (-not (Test-Path -LiteralPath $source)) { throw "Published executable not found: $source" }
  $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run PowerShell as Administrator.' }
  # A non-admin can create a folder under the standard ProgramData root on
  # Windows. Its owner retains WRITE_DAC even if the installer replaces the
  # DACL. Never treat an existing state folder or planted token as trusted just
  # because its content has a syntactically valid key or UUID.
  $adminSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
  $systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
  $currentAdminSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $trustedOwners = @($adminSid.Value, $systemSid.Value, 'S-1-5-19', $currentAdminSid)
  # Older releases may have been installed by a different local admin. Accept
  # their retained state without changing the secret or installation identity.
  # Membership lookup is a compatibility aid, not a substitute for ACL checks.
  try {
    $adminMembers = @(Get-LocalGroupMember -SID $adminSid -ErrorAction Stop)
    foreach ($member in $adminMembers) {
      if ($member.SID) { $trustedOwners += $member.SID.Value }
    }
  } catch {
    # Some Windows/PowerShell editions cannot enumerate local group members.
    # Known system, group, LocalService and current elevated owner SIDs remain
    # supported; otherwise fail closed with a remediation message.
  }
  function Test-TrustedStateSid([string]$Sid) {
    return (($trustedOwners -contains $Sid) -or $Sid.StartsWith('S-1-5-80-'))
  }
  function Assert-TrustedStateEntry([string]$Path, [bool]$IsDirectory) {
    $entry = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($IsDirectory -and -not $entry.PSIsContainer) {
      throw "Existing ComputerHostAgent state path is not a directory; refusing installation: $Path"
    }
    if (-not $IsDirectory -and $entry.PSIsContainer) {
      throw "Existing ComputerHostAgent state file is a directory; refusing installation: $Path"
    }
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "ComputerHostAgent state contains a reparse point; refusing to follow it: $Path"
    }
    # Inno Setup can launch Windows PowerShell 5.1 with restricted module
    # auto-loading. Get-Acl may fail there even though .NET access-control
    # methods work; mirror the existing SetAccessControl compatibility path.
    if ($PSVersionTable.PSVersion.Major -le 5) {
      if ($IsDirectory) {
        $security = ([IO.DirectoryInfo]::new($Path)).GetAccessControl()
      } else {
        $security = ([IO.FileInfo]::new($Path)).GetAccessControl()
      }
    } else {
      $security = Get-Acl -LiteralPath $Path -ErrorAction Stop
    }
    $owner = $security.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if (-not (Test-TrustedStateSid $owner)) {
      throw "ComputerHostAgent state has an untrusted owner; refusing to read or replace retained credentials: $Path. Review ownership and permissions manually; do not delete or rotate the existing state."
    }
    # An administrator-owned folder is not safe if it grants an unprivileged
    # account write/read access to a planted control-token.
    foreach ($rule in $security.Access) {
      if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) { continue }
      try {
        $subject = $rule.IdentityReference.Translate(
          [Security.Principal.SecurityIdentifier]).Value
      } catch {
        throw "ComputerHostAgent state has an unresolved access principal; refusing installation: $Path"
      }
      if (-not (Test-TrustedStateSid $subject)) {
        throw "ComputerHostAgent state grants access to an untrusted principal; refusing installation: $Path"
      }
    }
    if ($IsDirectory -and -not $security.AreAccessRulesProtected) {
      throw "Existing ComputerHostAgent state has an unprotected access list; refusing installation: $Path"
    }
  }
  $existing = Get-Service -Name $service -ErrorAction SilentlyContinue
  if ($existing) {
    $installedService = Get-CimInstance Win32_Service -Filter "Name='$service'"
    if ($installedService.StartName -ne 'NT AUTHORITY\LocalService' -or
        -not [string]::Equals($installedService.PathName.Trim().Trim('"'), $exe,
          [StringComparison]::OrdinalIgnoreCase)) {
      throw 'Existing service has unexpected binary/account; refusing to replace it.'
    }
  }
  if (Test-Path -LiteralPath $state) {
    Assert-TrustedStateEntry $state $true
    foreach ($name in @('control-token', 'installation-id', 'boot-session.json')) {
      $existingFile = Join-Path $state $name
      if (Test-Path -LiteralPath $existingFile) {
        Assert-TrustedStateEntry $existingFile $false
      }
    }
  }
  if ($PSCmdlet.ShouldProcess($service, ('Install service; power enabled: ' + [bool]$EnablePower))) {
    # Persisted UUID/boot state intentionally remains in ProgramData between upgrades.
    New-Item -ItemType Directory -Path $state -Force | Out-Null
    $acl = New-Object System.Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($adminSid)
    foreach ($sid in @('S-1-5-18','S-1-5-32-544','S-1-5-19')) {
      $identity = [Security.Principal.SecurityIdentifier]::new($sid)
      $rule = [Security.AccessControl.FileSystemAccessRule]::new(
        $identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
      $acl.AddAccessRule($rule)
    }
    # Windows PowerShell 5.1 provides DirectoryInfo.SetAccessControl via
    # .NET Framework without loading Microsoft.PowerShell.Security.
    # Inno's service child process can have restricted module auto-loading.
    # PowerShell 7 uses the equivalent Set-Acl cmdlet under .NET 10.
    if ($PSVersionTable.PSVersion.Major -le 5) {
      $directory = New-Object System.IO.DirectoryInfo($state)
      $directory.SetAccessControl($acl)
    } else {
      Set-Acl -LiteralPath $state -AclObject $acl
    }
  
    if ($existing -and $existing.Status -ne 'Stopped') {
      Stop-Service -Name $service -ErrorAction Stop
    }
    $configPath = Join-Path $programs 'appsettings.json'
    $preservedConfig = $null
    if (-not $UseExistingFiles -and (Test-Path -LiteralPath $configPath)) {
      # Keep customized settings across legacy PowerShell/ZIP upgrades.
      $preservedConfig = [IO.File]::ReadAllBytes($configPath)
    }
    if ($UseExistingFiles) {
      # Inno Setup owns the payload files and stops the service before
      # installing them. Never copy files over themselves.
      if (-not [string]::Equals(
          [IO.Path]::GetFullPath($PublishedDirectory).TrimEnd('\'),
          [IO.Path]::GetFullPath($programs).TrimEnd('\'),
          [StringComparison]::OrdinalIgnoreCase)) {
        throw '-UseExistingFiles requires PublishedDirectory to be the Program Files install directory.'
      }
    } else {
      New-Item -ItemType Directory -Path $programs -Force | Out-Null
      Copy-Item -Path (Join-Path $PublishedDirectory '*') -Destination $programs -Force -ErrorAction Stop
      if ($null -ne $preservedConfig) {
        [IO.File]::WriteAllBytes($configPath, $preservedConfig)
      }
    }
    # A service upgrade never enables power by accident. -EnablePower must be explicit.
    if (-not (Test-Path -LiteralPath $configPath)) { throw "Missing $configPath" }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $config.HostAgent | Add-Member -NotePropertyName EnablePowerControl -NotePropertyValue ([bool]$EnablePower) -Force
    # Windows PowerShell 5.1's Set-Content -Encoding utf8 adds a BOM.
  # Write BOM-less UTF-8 consistently from either 32- or 64-bit PowerShell.
  $json = $config | ConvertTo-Json -Depth 10
  [System.IO.File]::WriteAllText($configPath, $json + "`n",
    (New-Object System.Text.UTF8Encoding($false)))
    if ($EnablePower) {
      $tokenPath = Join-Path $state 'control-token'
      if (-not (Test-Path -LiteralPath $tokenPath)) {
        # Publish the complete secret atomically. A power loss must not leave
        # a partial control-token that prevents every later startup.
        $temporaryToken = Join-Path $state ('control-token.' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
          $keyBytes = New-Object byte[] 32
          $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
          try { $rng.GetBytes($keyBytes) } finally { $rng.Dispose() }
          $keyHex = ([BitConverter]::ToString($keyBytes)).Replace('-', '').ToLowerInvariant()
          [System.IO.File]::WriteAllText($temporaryToken, $keyHex + "`n", [System.Text.Encoding]::ASCII)
          try { [System.IO.File]::Move($temporaryToken, $tokenPath) }
          catch [System.IO.IOException] {
            if (-not (Test-Path -LiteralPath $tokenPath)) { throw }
            # Another concurrent install published the secret first.
          }
        } finally {
          if (Test-Path -LiteralPath $temporaryToken) {
            Remove-Item -LiteralPath $temporaryToken -Force -ErrorAction SilentlyContinue
          }
        }
      }
      $existingKey = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
      if ($existingKey -cnotmatch '^[a-fA-F0-9]{64}$') {
        throw 'Existing control-token invalid; refusing to rotate automatically.'
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
    # Add a unique service SID to the LocalService token before restricting
    # state permissions. Other unrelated LocalService processes must not read keys.
    & sc.exe sidtype $service unrestricted | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Unable to configure per-service SID' }
    # The firewall must match the actual HTTP listener, not just its default.
    $listenPort = 8765
    if ($null -ne $config.HostAgent.Port) {
      $parsedPort = 0
      if (-not [int]::TryParse([string]$config.HostAgent.Port, [ref]$parsedPort) -or
          $parsedPort -lt 1024 -or $parsedPort -gt 65535) {
        throw 'HostAgent:Port must be a valid TCP port (1024-65535).'
      }
      $listenPort = $parsedPort
    }
    if (-not $SkipFirewall) {
      Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
      $remoteScope = if ($HubIPv4) { $HubIPv4 } else { 'LocalSubnet' }
      New-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -DisplayName 'Computer Host Agent (trusted LAN)' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort $listenPort -Program $exe -Profile Private `
        -RemoteAddress $remoteScope | Out-Null
      Write-Warning "Firewall allows TCP $listenPort only from $remoteScope on PRIVATE networks. UDP/5353 mDNS remains subject to Windows network discovery policy."
    }
    # Per-service isolation: no generic LocalService/Users/Everyone ACL remains.
    $serviceSid = ([Security.Principal.NTAccount]::new('NT SERVICE', $service)).Translate(
      [Security.Principal.SecurityIdentifier])
    $identitySids = @(
      [Security.Principal.SecurityIdentifier]::new('S-1-5-18'),
      [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    )
    $secureDirectoryAcl = New-Object System.Security.AccessControl.DirectorySecurity
    $secureDirectoryAcl.SetAccessRuleProtection($true, $false)
    $secureDirectoryAcl.SetOwner($adminSid)
    foreach ($who in ($identitySids + @($serviceSid))) {
      $secureDirectoryAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $who, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    }
    if ($PSVersionTable.PSVersion.Major -le 5) {
      ([IO.DirectoryInfo]::new($state)).SetAccessControl($secureDirectoryAcl)
    } else { Set-Acl -LiteralPath $state -AclObject $secureDirectoryAcl }
    $tokenPath = Join-Path $state 'control-token'
    if (Test-Path -LiteralPath $tokenPath) {
      $keyAcl = New-Object System.Security.AccessControl.FileSecurity
      $keyAcl.SetAccessRuleProtection($true, $false)
      $keyAcl.SetOwner($adminSid)
      foreach ($who in $identitySids) {
        $keyAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
          $who, 'FullControl', 'Allow'))
      }
      $keyAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $serviceSid, 'Read', 'Allow'))
      if ($PSVersionTable.PSVersion.Major -le 5) {
        ([IO.FileInfo]::new($tokenPath)).SetAccessControl($keyAcl)
      } else { Set-Acl -LiteralPath $tokenPath -AclObject $keyAcl }
    }
    Start-Service -Name $service
    # PersistentIdentity creates this file as LocalService on first startup.
    # Its retained value is immutable, but ownership must not remain with a
    # generic service account: set Administrators as owner, while keeping the
    # per-service SID authorized to read/write the same file.
    $identityPath = Join-Path $state 'installation-id'
    for ($attempt = 0; $attempt -lt 20 -and -not (Test-Path -LiteralPath $identityPath); $attempt++) {
      Start-Sleep -Milliseconds 150
    }
    if (Test-Path -LiteralPath $identityPath -PathType Leaf) {
      $identityAcl = New-Object System.Security.AccessControl.FileSecurity
      $identityAcl.SetAccessRuleProtection($true, $false)
      $identityAcl.SetOwner($adminSid)
      foreach ($who in ($identitySids + @($serviceSid))) {
        $identityAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
          $who, 'FullControl', 'Allow'))
      }
      if ($PSVersionTable.PSVersion.Major -le 5) {
        ([IO.FileInfo]::new($identityPath)).SetAccessControl($identityAcl)
      } else { Set-Acl -LiteralPath $identityPath -AclObject $identityAcl }
    }
    Get-Service -Name $service | Format-Table Name,Status,StartType
    Write-Host "Identity/state kept in $state. Power commands enabled: $([bool]$EnablePower)"
    if ($EnablePower) { Write-Warning 'Privileged commands are enabled. Keep control-token secret; put it in SmartThings device preferences only over a trusted channel. Never share it in logs.' }
    Write-Warning 'Unsigned development build: use only on a test PC and do not distribute as a trusted public installer.'
  }
  
} catch {
  if ($DiagnosticPath) {
    try {
      # The diagnostic captures the exception type and message, not token contents.
      $message = 'ComputerHostAgent service installation failed: ' +
        $_.Exception.GetType().Name + ': ' + $_.Exception.Message
      [System.IO.File]::WriteAllText(
        [System.IO.Path]::GetFullPath($DiagnosticPath), $message,
        (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
  }
  throw
}
