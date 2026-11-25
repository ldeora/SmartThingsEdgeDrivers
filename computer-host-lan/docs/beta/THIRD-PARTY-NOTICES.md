# Computer Host LAN — third-party components and redistribution notices

This project is licensed under Apache-2.0 (see the project LICENSE).
The Windows application and its self-contained packages also incorporate
third-party software with different licenses. This document is a component
inventory, **not** a replacement for the complete upstream license texts.

| Component | Version / purpose | License / authoritative notice |
| --- | --- | --- |
| Zeroconf | NuGet 3.7.16; graphical Setup hub-discovery helper | MIT; https://www.nuget.org/packages/Zeroconf/3.7.16 |
| System.Reactive | Transitive Zeroconf dependency, resolved from NuGet | MIT; inspect resolved package and license in the release build |
| .NET runtime / ASP.NET Core libraries / Windows host | Self-contained Windows x64 deployment built with .NET 10 | Microsoft .NET Library License for Windows runtime distributions; https://github.com/dotnet/core/blob/main/license-information-windows.md |
| Microsoft.Extensions.Hosting.WindowsServices | NuGet 10.0.0; Windows Service integration | MIT; check the shipped package license at build time |
| Inno Setup 7 | Graphical installer bootstrapper and compiler | Inno Setup License; https://jrsoftware.org/inno-setup/faq and https://spdx.org/licenses/InnoSetup.html |

Zeroconf is © Claire Novotny 2016–2024 according to the package's NuGet
listing. Inno Setup credits Jordan Russell and Martijn Laan; retain the
original copyright/website notices in redistributed binaries. Do not
misrepresent the origin of these components.

**Release engineering requirement:** Before publishing a *stable* signed or
unsigned Windows bundle, capture the complete dependency graph (including
transitive packages), exact restored versions, original copyright notices,
the applicable full license texts and .NET runtime redistribution notices
from the actual compiled output/SDK. Include those notices in the delivered
Windows ZIP and installation documentation and review them in the final
release checklist. A SHA-256 checksum is an integrity check, not a code
signature or an independent provenance attestation.

Inno Setup's authors request commercial users purchase a license; the
publisher must decide whether the intended use is commercial. No such
purchase or final copyright sign-off is asserted here.

## Build-derived review evidence (#118)

The release-candidate Windows workflow captures the selected runtime-target
NuGet package identities, self-contained runtime download dependencies,
package license metadata and original available license/notice files from the
actual restore; it also captures the installed Inno Setup license, compiler
version/hash and SDK information. Each application inventory records the
published executable hash. The ordinary Linux installer CI captures the Go
module graph used for the test executable, compares it with the binary's
build information, and collects module-root and toolchain notices.
These are **review inputs**, not a complete notice bundle or legal sign-off.
Missing package directories/texts and expression/URL-only metadata require
manual resolution from authoritative version-matched upstream sources.
The final candidate's exact SDK/runtime/Go/compiler versions and all
redistributed components must be reviewed again, including any notices in
subdirectories, runtime packs installed outside NuGet and embedded assets.
No build evidence is automatically substituted for the required delivered
license texts. Inno Setup commercial-use classification remains a publisher
decision; see https://jrsoftware.org/inno-setup/purchase and the exact
installed LICENSE.TXT. Do not distribute a stable package until the reviewed
notices are included and packaging/installation tests confirm their presence.
