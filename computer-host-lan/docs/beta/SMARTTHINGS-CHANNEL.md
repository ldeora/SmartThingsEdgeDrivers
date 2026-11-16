# Computer Host LAN — SmartThings Edge beta channel

**Channel:** ARoedl SmartThings Edge Drivers  
**Channel ID:** `7a23289c-d1f8-42cc-ba10-4ffd219b89bb`  
**Driver:** Computer Host LAN  
**Driver ID:** `2ab3db0e-3b78-499e-bc3b-bcfa7f62b9f7`  
**Assigned SmartThings driver version:** `2026-11-16T00:05:31.405213849`  
**Invitation:** https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20

This is the existing public channel containing other community Edge drivers. No additional channel is needed for this beta. The invitation/channel IDs and assigned driver version were checked with `smartthings edge:channels:invites` and `smartthings edge:channels:drivers`. Another SmartThings account successfully installed **Computer Host LAN** through this invitation. This confirms channel distribution, **not** Windows 11 LAN discovery, profile presentation or power/WOL behavior.

## Install Computer Host LAN on the SmartThings hub

1. Open the [channel invitation](https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20) and sign in to the Samsung account associated with the intended hub.
2. Accept the invitation and **Enroll** the hub in the channel if it is not enrolled already.
3. Under the hub, choose **Available Drivers** and install **Computer Host LAN**.
4. Install the matching Computer Host LAN host agent from the [v0.5.1-beta.1 GitHub prerelease](https://github.com/ldeora/SmartThingsEdgeDrivers/releases/tag/computer-host-lan-v0.5.1-beta.1) on a separate test computer.
5. Ensure the hub can reach the host on **TCP 8765** and mDNS/UDP 5353 works on the trusted LAN. In SmartThings, select **Scan nearby**. The host advertises `_computerhost._tcp` and exposes protocol `/v2`.

**Important:** This shared channel also lists other drivers. Testers need only **Computer Host LAN**; installing unrelated drivers is unnecessary. This protocol-v2 driver is separate from the older protocol-v1 **Linux Host LAN** driver. Do not combine them.

On the owner's hub, the installed driver version matched the assigned channel version above. Assigned driver versions do not automatically update just because new source is committed to GitHub. For a new driver version, package it, assign it to the channel, and manage hub installation/update deliberately. Preserve the legacy driver/channel and avoid unexpected update of other published drivers.

Official SmartThings instructions: https://developer.smartthings.com/docs/devices/hub-connected/enroll-in-a-shared-channel/ and https://developer.smartthings.com/docs/devices/hub-connected/driver-channels/.
