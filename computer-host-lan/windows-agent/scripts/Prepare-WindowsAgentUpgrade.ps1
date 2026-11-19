# Used by the graphical installer BEFORE Inno replaces files.
# Avoid modifying an unrelated service that happens to use our service name.
[CmdletBinding()]
param([switch]$ValidateOnly, [string]$DiagnosticPath = '')
$ErrorActionPreference = 'Stop'
try {
  $ErrorActionPreference = 'Stop'
  $serviceName = 'ComputerHostAgent'
  $service = Get-CimInstance Win32_Service -Filter "Name='$serviceName'" -ErrorAction Stop
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
  if ($running.Status -ne 'Stopped') {
      Stop-Service -Name $serviceName -ErrorAction Stop
      (Get-Service -Name $serviceName).WaitForStatus(
          [System.ServiceProcess.ServiceControllerStatus]::Stopped,
          [TimeSpan]::FromSeconds(40))
  }
  # Preserve the previous working installation if file replacement or service
  # configuration fails. Snapshot resides beside the app in admin-only Program
  # Files, not in a world-writable temporary directory.
  $programs = Join-Path $programRoot 'Computer Host Agent'
  $backup = $programs + '.upgrade-rollback'
  if (Test-Path -LiteralPath $backup) {
    throw 'Previous rollback snapshot still exists; inspect or restore it before another upgrade.'
  }
  if (-not (Test-Path -LiteralPath $installedPath -PathType Leaf)) {
    throw 'Existing service binary is missing; refusing an unsafe upgrade.'
  }
  Copy-Item -LiteralPath $programs -Destination $backup -Recurse -Force -ErrorAction Stop
  try {
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
    Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
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
