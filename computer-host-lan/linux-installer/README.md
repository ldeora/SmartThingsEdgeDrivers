# Linux installer — non-privileged UX experiment

> **EXPERIMENT ONLY — NOT AN INSTALLER.** This Go program **does not** install, upgrade, configure, discover or connect anything. It does not inspect services, open a socket, read credentials, use sudo, or modify the host. Everything labeled as compatibility/discovery/installation is simulated.

This branch is stacked on [the Linux installer specification PR](../../docs/development/LINUX-INSTALLER-DESIGN.md) to test the initial forms and keyboard experience before privileged operations are designed. It is **not** part of any release or installation instructions for Computer Host LAN v1.0.0-rc.2.

## Try the experiment

Requires **Go 1.25+** to build the Huh v2 dependency. From `computer-host-lan/linux-installer/`:

```sh
go mod tidy
go run .
go run . -accessible
go run . -preview
go test ./...
```

The form widgets use `charm.land/huh/v2` (which uses Bubble Tea v2 internally). A custom Bubble Tea app shell will be considered once these interaction patterns have been evaluated. Examples use reserved TEST-NET addresses, not real discovered SmartThings hubs.

**Dependency-lock status:** The module pins a direct Huh version for this experiment. The `go.sum` / transitive dependency lock and license review must be generated, checked and committed before this changes from **draft spike** to a mergeable implementation. CI can validate the experiment independently by running `go mod tidy` first. Do not package this experiment or run it with elevated privileges.

## What to evaluate

- Is the short, wizard-like flow comfortable for both beginner and experienced users?
- Does accessible mode work acceptably with screen readers?
- Are the disabled-by-default power selections and separate WOL option obvious?
- Is manual IP validation helpful? Can users exit without confusion?
- How does it behave in narrow/monochrome terminals and over SSH?

## Next engineering steps (out of scope here)

Implement structured and privileged/unprivileged controller interfaces; real preflight, mDNS hub discovery and firewall diagnostics; installed-state detection; transactions with crash recovery; effective-config preservation, port configuration and post-install health verification; followed by real installation/hardware acceptance and signed/discoverable release assets.

The currently documented manual Linux install remains unchanged and supported.
