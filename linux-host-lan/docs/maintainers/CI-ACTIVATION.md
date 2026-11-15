# GitHub Actions activation (deferred)

`ci/github-actions-template.yml` is intentionally **not active** when this project is placed in the existing `SmartThingsEdgeDrivers/linux-host-lan/` subfolder. GitHub discovers Actions workflows only at repository root `.github/workflows/`.

When ready, create a root workflow dedicated to Linux Host LAN, add `defaults: run: working-directory: linux-host-lan`, adjust test and dependency paths, restrict triggers with `paths: ['linux-host-lan/**', '.github/workflows/linux-host-lan.yml']`, review the distribution container images, and pin third-party Actions to trusted commit hashes.

Do not treat workflow definitions as passed CI runs. Initial tested source only: Gentoo real hardware, Debian 13 source smoke.
