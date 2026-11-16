# Computer Host LAN (cross-platform)

This new project is intentionally separate from `linux-host-lan/`.

**Staging branch:** `feature/computer-host-lan`. The complete v0.5.1-dev.1 source tree is prepared as a downloadable archive and must be staged here before enabling GitHub Actions; this branch currently contains only the project scaffold.

Planned layout: `agent/` (Linux), `windows-agent/` (.NET 10), `edge-driver/` (shared Lua), `tests/` and `scripts/`.

The Linux reference v0.4.0-dev.1 has passed real SmartThings hub validation. Windows v0.2.0-alpha.1 introduces opt-in best-effort power commands, but **has not been compiled or hardware validated**. Do not deploy it to unattended computers.

When staging the complete source package, place it under `computer-host-lan/` and the GitHub Actions workflows under repository-root `.github/workflows/`. This work must not modify `linux-host-lan/`.
