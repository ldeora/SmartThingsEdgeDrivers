# Read-only, bounded health gate for graphical upgrades. Do not print identity or keys.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$ExpectedVersion, [int]$Attempts = 15)
$ErrorActionPreference = 'Stop'
$root = if ([Environment]::Is64BitOperatingSystem -and $env:ProgramW6432) { $env:ProgramW6432 } else { $env:ProgramFiles }
$configPath = Join-Path (Join-Path $root 'Computer Host Agent') 'appsettings.json'
$idPath = Join-Path (Join-Path $env:ProgramData 'ComputerHostAgent') 'installation-id'
if (-not (Test-Path -LiteralPath $configPath) -or -not (Test-Path -LiteralPath $idPath)) { throw 'Agent configuration or identity missing' }
$expectedId = (Get-Content -LiteralPath $idPath -Raw).Trim()
$guid = [Guid]::Empty
if (-not [Guid]::TryParseExact($expectedId, 'D', [ref]$guid)) { throw 'Invalid persisted installation identity' }
$cfg = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$port = 8765
if ($null -ne $cfg.HostAgent.Port) { $port = [int]$cfg.HostAgent.Port }
if ($port -lt 1024 -or $port -gt 65535) { throw 'Invalid configured agent port' }
$base = 'http://127.0.0.1:' + $port
for ($i = 0; $i -lt $Attempts; $i++) {
  try {
    $info = Invoke-RestMethod -Uri ($base + '/v2/info') -TimeoutSec 3
    $health = Invoke-RestMethod -Uri ($base + '/v2/health') -TimeoutSec 3
    if ($info.protocol -eq 'computer-host-agent' -and [int]$info.api_version -eq 2 -and
        $info.platform -eq 'windows' -and $info.agent_version -eq $ExpectedVersion -and
        $info.id -ceq $expectedId -and $health.id -ceq $expectedId -and
        $health.status -eq 'running') { Write-Host 'PASS health, identity and runtime version'; exit 0 }
  } catch { }
  Start-Sleep -Milliseconds 650
}
throw 'Agent health, version, or identity could not be confirmed; restore the previous installation.'
