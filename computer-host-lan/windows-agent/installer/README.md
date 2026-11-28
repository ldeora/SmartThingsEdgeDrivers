# Windows graphical installer

User instructions: [Install on Windows](../../docs/install-windows.md).
Maintainers: [Windows maintenance contract](../../docs/reference/architecture.md#windows-maintenance-contract)
and [development and release engineering](../../docs/development.md).
Inno Setup 7 builds the version-matched x64 Setup; the native CI workflow
tests the installer, including upgrade/recovery, actual firewall and
service state, and notices. No ordinary CI artifact is a public release.
