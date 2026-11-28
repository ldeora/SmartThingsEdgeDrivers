# Windows Host Agent

Users: [Install on Windows](../docs/install-windows.md),
[maintenance](../docs/upgrade.md), [security](../SECURITY.md).
Do not delete or re-pair a working device during normal upgrades.

## Build

```powershell
dotnet build .\ComputerHost.WindowsAgent\ComputerHost.WindowsAgent.csproj -c Release
dotnet run --project .\ComputerHost.WindowsAgent.Tests\ComputerHost.WindowsAgent.Tests.csproj -c Release
.\scripts\Publish-WindowsAgent.ps1 -Runtime win-x64
.\scripts\Smoke-WindowsAgent.ps1 -Executable "$PWD\publish\win-x64\ComputerHost.WindowsAgent.exe"
```

Builds use .NET 10. Published x64 binaries are self-contained, so ordinary testers do not need the SDK. The smoke test disables mDNS and never sends valid power commands.

Development console runs must use a separate pre-created private state
directory with a protected DACL for the invoking user and trusted
administrators/SYSTEM. The installed LocalService agent requires the
installer-provisioned state directory and exact service SID. A service
invocation cannot choose console policy. Never use production state for
development; the smoke script provisions a disposable fixture and never
sends an authenticated power command.

See [architecture and Windows maintenance contract](../docs/reference/architecture.md)
and [development/release process](../docs/development.md).
