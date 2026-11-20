# Used by the graphical installer BEFORE Inno replaces files.
# Avoid modifying an unrelated service that happens to use our service name.
[CmdletBinding()]
param([switch]$ValidateOnly, [string]$DiagnosticPath = '')
$ErrorActionPreference = 'Stop'
try {
  $ErrorActionPreference = 'Stop'
  $serviceName = 'ComputerHostAgent'
  $service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction Stop
  # Fail before stopping a healthy service if an earlier upgrade was interrupted.
  $programRoot = if ([Environment]::Is64BitOperatingSystem -and $env:ProgramW6432) { $env:ProgramW6432 } else { $env:ProgramFiles }
  $backup = (Join-Path $programRoot 'Computer Host Agent') + '.upgrade-rollback'
  if (Test-Path -LiteralPath $backup) {
    throw 'An unfinished upgrade snapshot exists. Recover it with Restore-WindowsAgentUpgrade.ps1 -Mode Restore before retrying Setup.'
  }
  if (-not $service) { return }
  # Inno Setup invokes Windows PowerShell from a 32-bit bootstrapper on some
  # systems. ProgramFiles in that process may mean Program Files (x86).
  # ProgramW6432 always identifies the 64-bit installation root on x64.
  $programRoot = if ([Environment]::Is64BitOperatingSystem -and $env:ProgramW6432) {
    $env:ProgramW6432
  } else {
    $env:ProgramFiles
  }
  $installedPath = Join-Path (Join-Path $programRoot 'Computer Host Agent') 'ComputerHost.WindowsAgent.exe'
  if ($service.StartName -ne 'NT AUTHORITY\LocalService') {
      throw 'Existing service is not owned by the expected LocalService account; refusing to replace.'
  }
  # Normalize quotes without accepting a differently located executable.
  $path = $service.PathName.Trim().Trim('"')
  if (-not [string]::Equals($path, $installedPath, [StringComparison]::OrdinalIgnoreCase)) {
      throw 'Existing service executable path does not match Computer Host Agent; refusing to replace.'
  }
  if ($ValidateOnly) { Write-Host 'PASS existing agent service ownership validation'; return }
  $running = Get-Service -Name $serviceName -ErrorAction Stop
  $wasRunning = $running.Status -ne 'Stopped'
  $programs = Join-Path $programRoot 'Computer Host Agent'
  $backup = $programs + '.upgrade-rollback'
  $snapshotAttempted = $false
  try {
    if ($wasRunning) {
      Stop-Service -Name $serviceName -ErrorAction Stop
      (Get-Service -Name $serviceName).WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Stopped,
        [TimeSpan]::FromSeconds(40))
    }
    if (-not (Test-Path -LiteralPath $installedPath -PathType Leaf)) {
      throw 'Existing service binary is missing; refusing an unsafe upgrade.'
    }
    # A staging failure is not an upgrade: remove only our NEW partial snapshot
    # and restore the original service before returning an error to Setup.
    $snapshotAttempted = $true
    Copy-Item -LiteralPath $programs -Destination $backup -Recurse -Force -ErrorAction Stop
    $rule = Get-NetFirewallRule -Name 'ComputerHostAgent-TCP8765' -ErrorAction SilentlyContinue
    $saved = @{ Present = [bool]$rule }
    if ($rule) {
      $address = $rule | Get-NetFirewallAddressFilter
      $ports = $rule | Get-NetFirewallPortFilter
      $saved.RemoteAddress = @($address.RemoteAddress)
      $saved.LocalPort = @($ports.LocalPort)
      $saved.Profile = [string]$rule.Profile
    }
    [IO.File]::WriteAllText((Join-Path $backup 'firewall-rollback.json'),
      ($saved | ConvertTo-Json -Depth 5), [Text.Encoding]::UTF8)
  } catch {
    $stagingFailure = $_.Exception.Message
    $cleanupFailure = ''
    $restartFailure = ''
    if ($snapshotAttempted -and (Test-Path -LiteralPath $backup)) {
      try { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop }
      catch { $cleanupFailure = $_.Exception.Message }
    }
    if ($wasRunning) {
      try {
        $current = Get-Service -Name $serviceName -ErrorAction Stop
        if ($current.Status -ne 'Running') {
          Start-Service -Name $serviceName -ErrorAction Stop
          $current.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running,
            [TimeSpan]::FromSeconds(40))
        }
      } catch { $restartFailure = $_.Exception.Message }
    }
    if ($cleanupFailure -or $restartFailure) {
      throw "Upgrade preparation failed: $stagingFailure. Snapshot cleanup: $cleanupFailure. Original service restart: $restartFailure."
    }
    throw
  }
} catch {
  # Only service-management details, no authentication data or UUIDs.
  if ($DiagnosticPath) {
    try {
      [System.IO.File]::WriteAllText([System.IO.Path]::GetFullPath($DiagnosticPath),
        ('ComputerHostAgent preparation failed: ' + $_.Exception.Message),
        [System.Text.Encoding]::UTF8)
    } catch { }
  }
  throw
}
