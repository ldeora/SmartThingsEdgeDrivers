# Computer Host LAN — SmartThings Edge beta channel

**Channel:** ARoedl SmartThings Edge Drivers  
**Channel ID:** `7a23289c-d1f8-42cc-ba10-4ffd219b89bb`  
**Driver:** Computer Host LAN  
**Driver ID:** `2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7`  
**Last owner-reported installed hub version (rc.1):** `2026-11-20T23:22:52.284035939`; exact rc.2 channel version **not independently confirmed**  
**Invitation:** https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20

This is the existing public channel containing other community Edge drivers. No additional channel is needed for this beta. The invitation/channel IDs and assigned driver version were checked with `smartthings edge:channels:invites` and `smartthings edge:channels:drivers`. Another SmartThings account successfully installed **Computer Host LAN** through this invitation. This confirms channel distribution, **not** Windows 11 LAN discovery, profile presentation or power/WOL behavior.

## Install Computer Host LAN on the SmartThings hub

1. Open the [channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) and sign in to the Samsung account associated with the intended hub.
2. Accept the invitation and **Enroll** the hub in the channel if it is not enrolled already.
3. Under the hub, choose **Available Drivers** and install **Computer Host LAN**.
4. Install the matching agent from the [published v1.0.0-rc.2 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v1.0.0-rc.2) on a separate computer. **GitHub publication does not prove the rc.2 Edge driver has been assigned to this channel or installed on this hub.** Verify actual channel and installed driver versions separately before calling testing version-matched.
5. Ensure the hub can reach the host on **TCP 8765** and mDNS/UDP 5353 works on the trusted LAN. In SmartThings, select **Scan nearby**. The host advertises `_computerhost._tcp` and exposes protocol `/v2`.

**Important:** This shared channel also lists other drivers. Testers need only **Computer Host LAN**; installing unrelated drivers is unnecessary. This protocol-v2 driver is separate from the older protocol-v1 **Linux Host LAN** driver. Do not combine them.

The publisher reported the rc.1 installed hub version above. **No exact rc.2 channel assignment timestamp is documented here yet.** Verify it with `smartthings edge:channels:drivers` and `smartthings edge:drivers:installed --hub HUB_ID --verbose`, then record the actual build. Channel versions do not change just because new source was committed. Preserve the original driver ID/channel and existing computer devices.

Official SmartThings instructions: https://developer.smartthings.com/docs/devices/hub-connected/enroll-in-a-shared-channel/ and https://developer.smartthings.com/docs/devices/hub-connected/driver-channels/.
