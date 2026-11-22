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
  # ProgramData permits standard users to create subdirectories. The state
  # directory must therefore be created with its final protected DACL in the
  # CreateDirectory call; never create it first and tighten permissions later.
  $adminSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
  $systemSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
  $localServiceSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-19')
  $currentAdminSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $trustedAdminSids = @($adminSid.Value, $systemSid.Value, $currentAdminSid)
  # Preserve retained state installed by a different local administrator.
  try {
    $adminMembers = @(Get-LocalGroupMember -SID $adminSid -ErrorAction Stop)
    foreach ($member in $adminMembers) {
      if ($member.SID) { $trustedAdminSids += $member.SID.Value }
    }
  } catch {
    # Some PowerShell/Windows editions cannot enumerate local group members.
    # The built-in groups and current elevated administrator remain trusted.
  }
  $trustedAdminSids = @($trustedAdminSids | Sort-Object -Unique)

  # sc.exe computes the SID for a service name even before that service is
  # registered. Trust only this service's SID, never every S-1-5-80-* SID.
  $serviceSidOutput = (& sc.exe showsid $service 2>&1 | Out-String)
  if ($LASTEXITCODE -ne 0) {
    throw 'Unable to calculate the ComputerHostAgent service SID; refusing to handle persistent state.'
  }
  $serviceSidMatch = [regex]::Match($serviceSidOutput, 'S-1-5-80-(?:\d+-){4}\d+')
  if (-not $serviceSidMatch.Success) {
    throw 'Windows did not return a valid ComputerHostAgent service SID; refusing to handle persistent state.'
  }
  $serviceSid = [Security.Principal.SecurityIdentifier]::new($serviceSidMatch.Value)
  $identitySids = @($systemSid, $adminSid)

  $stateRecovery = 'If this PC has never had Computer Host LAN installed, inspect the folder and remove it only after confirming it contains no legitimate installation state. For an existing installation, preserve installation-id. If an untrusted account could read or modify control-token, treat that key as compromised, replace it deliberately, and update the SmartThings controlKey preference. The installer never deletes or rotates credentials automatically.'
  function Assert-TrustedStateEntry([string]$Path,
    [ValidateSet('Directory','ControlToken','AgentFile')][string]$Kind) {
    $entry = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    $isDirectory = $Kind -eq 'Directory'
    if ($isDirectory -and -not $entry.PSIsContainer) {
      throw "ComputerHostAgent state path is not a directory; refusing installation: $Path"
    }
    if (-not $isDirectory -and $entry.PSIsContainer) {
      throw "ComputerHostAgent state file is a directory; refusing installation: $Path"
    }
    if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw "ComputerHostAgent state contains a reparse point; refusing to follow it: $Path. $stateRecovery"
    }
    # Inno Setup may launch Windows PowerShell 5.1 with restricted module
    # auto-loading, so use .NET access-control APIs on 5.1.
    if ($PSVersionTable.PSVersion.Major -le 5) {
      if ($isDirectory) {
        $security = ([IO.DirectoryInfo]::new($Path)).GetAccessControl()
      } else {
        $security = ([IO.FileInfo]::new($Path)).GetAccessControl()
      }
    } else {
      $security = Get-Acl -LiteralPath $Path -ErrorAction Stop
    }
    switch ($Kind) {
      'Directory' {
        $ownerAllowedSids = $trustedAdminSids
        $aceAllowedSids = @($trustedAdminSids + $serviceSid.Value)
      }
      'ControlToken' {
        $ownerAllowedSids = $trustedAdminSids
        $aceAllowedSids = @($trustedAdminSids + $serviceSid.Value)
      }
      'AgentFile' {
        # LocalService owns files created by the agent (not the directory or
        # control-token). Permit only this service SID, not arbitrary services.
        $agentFileSids = @($trustedAdminSids + $localServiceSid.Value + $serviceSid.Value)
        $ownerAllowedSids = $agentFileSids
        $aceAllowedSids = $agentFileSids
      }
    }
    $owner = $security.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($ownerAllowedSids -notcontains $owner) {
      throw "ComputerHostAgent state has an untrusted owner; refusing to read or replace retained credentials: $Path. $stateRecovery"
    }
    foreach ($rule in $security.Access) {
      if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) { continue }
      try {
        $subject = $rule.IdentityReference.Translate(
          [Security.Principal.SecurityIdentifier]).Value
      } catch {
        throw "ComputerHostAgent state has an unresolved access principal; refusing installation: $Path. $stateRecovery"
      }
      if ($aceAllowedSids -notcontains $subject) {
        throw "ComputerHostAgent state grants access to an untrusted principal; refusing installation: $Path. $stateRecovery"
      }
    }
    if ($isDirectory -and -not $security.AreAccessRulesProtected) {
      throw "Existing ComputerHostAgent state has an unprotected access list; refusing installation: $Path. $stateRecovery"
    }
  }
  function Set-StateDirectoryAcl([string]$Path, $Acl) {
    if ($PSVersionTable.PSVersion.Major -le 5) {
      ([IO.DirectoryInfo]::new($Path)).SetAccessControl($Acl)
    } else {
      Set-Acl -LiteralPath $Path -AclObject $Acl
    }
  }
  function Set-StateFileAcl([string]$Path, $Acl) {
    if ($PSVersionTable.PSVersion.Major -le 5) {
      ([IO.FileInfo]::new($Path)).SetAccessControl($Acl)
    } else {
      Set-Acl -LiteralPath $Path -AclObject $Acl
    }
  }
  function Assert-ExistingStateFiles {
    foreach ($name in @('control-token', 'installation-id', 'boot-session.json')) {
      $existingFile = Join-Path $state $name
      if (Test-Path -LiteralPath $existingFile) {
        $kind = if ($name -eq 'control-token') { 'ControlToken' } else { 'AgentFile' }
        Assert-TrustedStateEntry $existingFile $kind
      }
    }
  }

  $stateDirectoryAcl = New-Object System.Security.AccessControl.DirectorySecurity
  $stateDirectoryAcl.SetAccessRuleProtection($true, $false)
  $stateDirectoryAcl.SetOwner($adminSid)
  foreach ($sid in @($systemSid, $adminSid, $serviceSid)) {
    $stateDirectoryAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
      $sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
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
    Assert-TrustedStateEntry $state 'Directory'
    Assert-ExistingStateFiles
  }
  if ($PSCmdlet.ShouldProcess($service, ('Install service; power enabled: ' + [bool]$EnablePower))) {
    # Stop the existing agent before changing its persistent-state ACLs.
    if ($existing -and $existing.Status -ne 'Stopped') {
      Stop-Service -Name $service -ErrorAction Stop
    }
    # This API creates the directory with its final DACL atomically. If an
    # attacker wins the path-creation race, an existing directory is returned
    # unchanged and the immediate owner/ACL/reparse check below rejects it.
    if ($PSVersionTable.PSVersion.Major -le 5) {
      [void][IO.Directory]::CreateDirectory($state, $stateDirectoryAcl)
    } else {
      [System.IO.FileSystemAclExtensions]::Create(
        [IO.DirectoryInfo]::new($state), $stateDirectoryAcl)
    }
    Assert-TrustedStateEntry $state 'Directory'
    # Canonicalize an already-existing, previously validated state directory.
    Set-StateDirectoryAcl $state $stateDirectoryAcl
    Assert-TrustedStateEntry $state 'Directory'
    Assert-ExistingStateFiles
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
    # Revalidate the directory and every retained state file after ACL lockdown,
    # immediately before any existing control key can be read.
    Assert-TrustedStateEntry $state 'Directory'
    Assert-ExistingStateFiles
    if ($EnablePower) {
      $tokenPath = Join-Path $state 'control-token'
      if (-not (Test-Path -LiteralPath $tokenPath)) {
        # Publish the complete secret atomically. The state directory is
        # already protected, so no standard user can plant the destination.
        $temporaryToken = Join-Path $state ('control-token.' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
          $keyBytes = New-Object byte[] 32
          $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
          try { $rng.GetBytes($keyBytes) } finally { $rng.Dispose() }
          $keyHex = ([BitConverter]::ToString($keyBytes)).Replace('-', '').ToLowerInvariant()
          [System.IO.File]::WriteAllText($temporaryToken, $keyHex + [Environment]::NewLine, [System.Text.Encoding]::ASCII)
          try { [System.IO.File]::Move($temporaryToken, $tokenPath) }
          catch [System.IO.IOException] {
            if (-not (Test-Path -LiteralPath $tokenPath)) { throw }
            # A concurrent elevated installer may have published the key first.
          }
        } finally {
          if (Test-Path -LiteralPath $temporaryToken) {
            Remove-Item -LiteralPath $temporaryToken -Force -ErrorAction SilentlyContinue
          }
        }
      }
      $keyAcl = New-Object System.Security.AccessControl.FileSecurity
      $keyAcl.SetAccessRuleProtection($true, $false)
      $keyAcl.SetOwner($adminSid)
      foreach ($who in $identitySids) {
        $keyAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
          $who, 'FullControl', 'Allow'))
      }
      $keyAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $serviceSid, 'Read', 'Allow'))
      Set-StateFileAcl $tokenPath $keyAcl
      Assert-TrustedStateEntry $tokenPath 'ControlToken'
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
    # Service metadata shown in services.msc; no effect on runtime configuration.
    # Apply it on both new installs and upgrades without making it a release blocker.
    $serviceDescription = 'Provides local computer status and system monitoring to Samsung SmartThings, with optional remote power management.'
    try {
      & sc.exe description $service $serviceDescription | Out-Host
      if ($LASTEXITCODE -ne 0) {
        Write-Warning 'Unable to update ComputerHostAgent service description; continuing installation.'
      }
    } catch {
      Write-Warning 'Unable to update ComputerHostAgent service description; continuing installation.'
    }
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
      # Loopback /v2/health cannot detect a hub blocked by a Public profile.
      # This check only warns; never silently switch the Windows network to
      # Private or widen the firewall rule to Public.
      try {
        $networkProfiles = @(Get-NetConnectionProfile -ErrorAction Stop)
        $publicProfiles = @($networkProfiles | Where-Object {
          $_.NetworkCategory -eq 'Public' -and
          $_.IPv4Connectivity -ne 'Disconnected'
        })
        if ($publicProfiles.Count -gt 0) {
          Write-Warning 'An active Windows network profile is PUBLIC. The Computer Host firewall rule is PRIVATE-only, so SmartThings hub connections over that interface may be blocked even when localhost health checks pass. If this is a trusted home network, review its profile in Windows Settings > Network & internet; do not disable the firewall.'
        }
      } catch {
        # The native Inno PowerShell host can restrict module auto-loading.
        # Firewall installation must not fail due to optional diagnostics.
        Write-Warning 'Unable to inspect the Windows network profile. Verify that the hub-facing interface is PRIVATE; this installer does not open PUBLIC inbound access.'
      }
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
    if (Test-Path -LiteralPath $identityPath) {
      Assert-TrustedStateEntry $identityPath 'AgentFile'
    }
    $bootSessionPath = Join-Path $state 'boot-session.json'
    if (Test-Path -LiteralPath $bootSessionPath) {
      Assert-TrustedStateEntry $bootSessionPath 'AgentFile'
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
