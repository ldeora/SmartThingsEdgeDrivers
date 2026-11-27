# Computer Host LAN — third-party components and redistribution notices

This project is licensed under Apache-2.0 (see the project LICENSE).
The Windows application, its self-contained packages and the Linux installer
also incorporate third-party software with different licenses. This document
is a component inventory, **not** a replacement for the complete upstream
license texts.

## Linux installer

The Linux installer is a statically linked Go program. Every release ships
`computer-host-lan-v<version>-linux-x64-third-party-notices.txt`, covered by
`SHA256SUMS.txt`, with the full licence text of each component compiled into
it; the same file is `linux-installer/THIRD-PARTY-NOTICES.txt` in the source
and documentation archives. It is generated from the module graph of the
release build by `scripts/ci/linux_third_party_notices.py`, and CI fails when
a dependency changes without a matching update or when the built binary links
a module the file does not name.

| Component | License |
| --- | --- |
| Go standard library and runtime | BSD-3-Clause |
| `golang.org/x/sys`, `golang.org/x/sync` | BSD-3-Clause |
| `github.com/atotto/clipboard` | BSD-3-Clause |
| Charm modules: `charm.land/bubbletea/v2`, `huh/v2`, `bubbles/v2`, `lipgloss/v2`; `github.com/charmbracelet/ultraviolet`, `colorprofile`, `x/ansi`, `x/term`, `x/termios`, `x/windows`, `x/exp/ordered`, `x/exp/strings` | MIT |
| Other modules: `catppuccin/go`, `clipperhouse/displaywidth`, `clipperhouse/uax29/v2`, `dustin/go-humanize`, `lucasb-eyer/go-colorful`, `mattn/go-runewidth`, `mitchellh/hashstructure/v2`, `muesli/cancelreader`, `rivo/uniseg`, `xo/terminfo` | MIT |

Exact module versions are listed in the notices file and in the release's
`build-info.json`.

## Windows application

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

**Release engineering follow-up (#118):** Improve the dependency inventory
and notice bundles using available build-derived evidence. The completeness
of this automated collection and the packaging improvements are best-effort
for v1.0, not release gates. Keep existing notices and honor applicable
upstream redistribution conditions; this project scheduling decision does
not waive any license terms or establish legal compliance. A SHA-256
checksum is an integrity check, not a code signature or an independent
provenance attestation.

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
installed LICENSE.TXT. Evidence collection and upload are advisory CI steps
with bounded timeouts; failures remain visible and incomplete collections
are not uploaded as complete evidence. Fixture tests remain required.
Continue notice-bundle improvements and packaging verification under #118
without gating v1.0 on completion of that automation.
