# Read-only SHA256 verification. Checksums are NOT Authenticode signatures.
[CmdletBinding()]
param([string]$Manifest = (Join-Path (Split-Path $PSScriptRoot -Parent) 'FILES.sha256'))
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) { throw "No checksum manifest: $Manifest" }
$root = Split-Path -Parent (Resolve-Path -LiteralPath $Manifest)
$seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$ok = 0
foreach ($line in (Get-Content -LiteralPath $Manifest)) {
  if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { continue }
  if ($line -cnotmatch '^([a-fA-F0-9]{64})  (.+)$') { throw 'Invalid checksum manifest line' }
  $expected = $Matches[1].ToLowerInvariant()
  $relative = $Matches[2]
  if ($relative -match '(^|[\\/])\.\.([\\/]|$)' -or [IO.Path]::IsPathRooted($relative) -or
      $relative -match '[:*?"<>|]') { throw 'Unsafe checksum path' }
  if (-not $seen.Add($relative)) { throw "Duplicate manifest entry: $relative" }
  $path = Join-Path $root $relative
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing file: $relative" }
  $found = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($found -ne $expected) { throw "Checksum mismatch: $relative" }
  $ok++
}
if ($ok -eq 0) { throw 'Empty checksum manifest' }
Write-Host "PASS: $ok file checksums verified. SHA-256 alone does not establish publisher identity."
