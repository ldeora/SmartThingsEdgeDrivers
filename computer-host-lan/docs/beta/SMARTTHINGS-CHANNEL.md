> **Historical v0.3.1-beta.1 beta document.** This page describes the previous Linux-only
> integration and is **not** a valid installation or protocol guide for
> v0.4.0-dev.1. Use root `README.md`, `PROTOCOL.md` and `INSTALLATION.md`.

# SmartThings beta channel and device presentation

The Linux Host Edge Driver is **v0.2.9** in this candidate. The integration archive's version change does not require repackaging/installing that driver on existing functioning hubs. Publisher-owned custom capabilities are defined under `oceancircle09600` and their presentation/locale files are included in `edge-driver/custom-capabilities/`.

## Channel-owner preparation

1. Pick a **separate beta/test channel** rather than replacing the stable driver for existing users. Verify channel ownership and whether its invitation settings fit a limited volunteer pilot.
2. Verify all six capabilities and their presentations exist in `oceancircle09600`; verify the German and English presentations using the owner's SmartThings account. Do not instruct public testers to register their own capabilities.
3. Package the tested Edge Driver in the selected channel. CLI commands from the official channel documentation include:

   ```sh
   smartthings edge:drivers:package edge-driver --install
   smartthings edge:channels:assign
   smartthings edge:channels:invites:create
   ```

   Confirm the channel and driver IDs interactively. No channel invitation URL is pre-filled in this archive.
4. Enroll a **different tester account and hub** through the invite and verify an actual first-time installation and advanced monitoring profile. A working developer account alone does not prove that a public tester can see the six custom capabilities.
5. Verify updates: a channel assignment pins a driver version; publishing a newer package does not automatically update the version already installed on every tester hub. Document the update instructions.
6. Only after license, security, distro and tester gates are met, distribute the invitation and beta installation archive together.

## Tester onboarding

An invited user accepts the driver-channel invitation, signs in, enrolls the hub and installs the driver. The Linux agent is installed separately from a trusted source. The Linux computer must be discoverable via Avahi/mDNS and reachable on TCP 8765 from the hub. See `START-HERE.md`.

Official references:
- https://developer.smartthings.com/docs/devices/hub-connected/driver-channels
- https://developer.smartthings.com/docs/devices/hub-connected/enroll-in-a-shared-channel/
