# Build from a Windows machine with the .NET 10 SDK. Not a release-signing step.
[CmdletBinding()]
param(
  [ValidateSet('win-x64','win-arm64')][string]$Runtime = 'win-x64'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$project = Join-Path $root 'ComputerHost.WindowsAgent/ComputerHost.WindowsAgent.csproj'
$out = Join-Path $root "publish/$Runtime"
dotnet publish $project --configuration Release --runtime $Runtime --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=none --output $out
if ($LASTEXITCODE -ne 0) { throw 'dotnet publish failed' }
Write-Host "Published Windows agent in $out"
