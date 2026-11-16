# Computer Host LAN — beta SmartThings Edge channel

This project is **not** the older Linux Host LAN driver. Publisher: `oceancircle09600` custom capabilities; driver package key `computer-host-lan`; discovery service `_computerhost._tcp`; separate Linux and Windows profiles. The channel invitation URL is **not yet issued or validated**.

## Publisher preparation (owner)

1. Confirm six custom capability IDs and English/German presentations are available in the publisher's SmartThings account (see `edge-driver/custom-capabilities/REGISTER.md`). Ordinary testers must not register these.
2. Create or select a **Computer Host LAN-specific beta Edge driver channel**. Keep the original Linux Host LAN channel/driver untouched.
3. From `computer-host-lan/` package and install the `edge-driver/` using the SmartThings CLI. Record the installed driver ID, package version, channel assignment and hub firmware.
4. Assign the tested package version to the beta channel; create a channel invitation using SmartThings CLI ```smartthings edge:channels:invites:create``` after confirming channel selection. Do not invent an invitation URL.
5. **Before public announcement:** open that invitation with a *second* SmartThings account/hub if available, install the driver on its hub, and verify app presentation and first discovery. A working owner's account alone is insufficient evidence of cross-account custom capability UI.
6. Record how to publish a newer driver version and how testers can update channel installations. Provide an uninstall/rollback path for existing devices.

## Tester onboarding (after invite is live)

Accept the published invitation, select a suitable hub, install **Computer Host LAN**, then install the host agent separately and use **Scan nearby**. Host must be reachable on TCP8765 and advertise `_computerhost._tcp` via mDNS UDP5353. Manual `hostOverride` is *not* a way to create the initial device.

**Placeholders to fill only after validation:** beta channel invitation URL, channel name/ID, driver version/ID, supported hub requirements and first-time enrollment notes.

Official SmartThings docs: https://developer.smartthings.com/docs/devices/hub-connected/driver-channels and https://developer.smartthings.com/docs/devices/hub-connected/enroll-in-a-shared-channel/.
