# Aqara FP300 Zigbee Edge Driver for SmartThings

Community SmartThings Edge Driver for the **Aqara Presence Multi-Sensor FP300** (`lumi.sensor_occupy.agl8`) in **Zigbee mode**.

This package is a dedicated driver for the FP300 and exposes far more of the device's real functionality than a generic sensor pairing. In particular, it handles Aqara's manufacturer-specific Zigbee attributes for presence tuning, detection range, target distance tracking, sampling/reporting behavior, and other advanced device options.

## What this driver supports

This driver exposes the FP300 in SmartThings with the following main capabilities:

- **Presence**
- **PIR motion**
- **Battery**
- **Temperature**
- **Relative humidity**
- **Illuminance**
- **Target distance** via the custom capability `oceancircle09600.aqaratargetdistance`
- **Refresh**

It also supports both known Zigbee manufacturer variants used by this device:

- `Aqara / lumi.sensor_occupy.agl8`
- `LUMI / lumi.sensor_occupy.agl8`

## Why this driver exists

The FP300 is not just a basic occupancy sensor. In Zigbee mode it exposes a large set of **Aqara-specific attributes** through manufacturer-specific cluster `0xFCC0` (manufacturer code `0x115F`).

That means a stock or generic integration usually sees only the obvious standard sensors, while many of the interesting FP300 features stay inaccessible or only partially implemented.

This driver is built specifically to bridge that gap in SmartThings by:

- mapping **presence** and **PIR motion** separately
- exposing **target distance**
- applying **advanced configuration preferences**
- reading and writing Aqara-specific attributes directly
- verifying important writes with follow-up readback logic

## Device overview

According to Aqara, the FP300 combines:

- **dual-sensor presence detection** using PIR and **60 GHz mmWave**
- a **120° field of view**
- a maximum detection range of **up to 6 m**
- built-in **temperature**, **humidity**, and **ambient light** sensing
- power from **2× CR2450 batteries**
- dual-protocol hardware (**Zigbee** and **Thread/Matter**)

This driver targets the device specifically in **Zigbee mode**.

## Requirements

- A **SmartThings Hub** with Zigbee / Edge driver support
- The FP300 in **Zigbee mode**
- A SmartThings account and app
- This driver installed through your own Edge channel or a shared driver channel

## Installation

### Option 1: Install from a shared Edge channel

If the driver is already published to a shared channel:

1. Open https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20
2. Accept the invite and enroll the target hub.
3. Open **Available Drivers** for that hub.
4. Install **Aqara FP300 Presence Sensor**.
5. Pair the FP300 in **Zigbee mode**.

If the device was already paired with a different driver, it is often best to **remove and re-add it**, or manually switch it to this driver if SmartThings allows it.

### Option 2: Build and publish it yourself

If you want to use this repository directly:

1. Clone your repository.
2. Package the driver:
   ```bash
   smartthings edge:drivers:package aqara-fp300
   ```
3. Assign the packaged driver to one of your channels.
4. Enroll your hub into that channel.
5. Install the driver on the hub.
6. Pair the FP300 in Zigbee mode.

## Core package files

The main driver package is built from these core files:

```text
aqara-fp300/
├── config.yml
├── fingerprints.yml
├── profiles/
│   └── aqara-fp300.yml
└── src/
    └── init.lua
```

## Fingerprints

The driver includes dedicated Zigbee fingerprints for:

```yaml
zigbeeManufacturer:
  - id: "Aqara/lumi.sensor_occupy.agl8"
    manufacturer: Aqara
    model: lumi.sensor_occupy.agl8
    deviceProfileName: aqara-fp300
  - id: "LUMI/lumi.sensor_occupy.agl8"
    manufacturer: LUMI
    model: lumi.sensor_occupy.agl8
    deviceProfileName: aqara-fp300
```

## Exposed SmartThings capabilities

The included device profile exposes these capabilities on the main component:

- `presenceSensor`
- `motionSensor`
- `battery`
- `temperatureMeasurement`
- `relativeHumidityMeasurement`
- `illuminanceMeasurement`
- `oceancircle09600.aqaratargetdistance`
- `refresh`

Category:

- `PresenceSensor`

## Preferences and configuration options

One of the biggest strengths of this driver is the amount of device-side configuration it exposes.

### Calibration

- **Temperature offset**
- **Humidity offset**

### Presence and motion tuning

- **Presence detection mode**
  - Both
  - mmWave only
  - PIR only
- **Motion sensitivity**
  - Low
  - Medium
  - High
- **Absence delay**
- **PIR detection interval**

### Aqara AI features

- **AI adaptive sensitivity**
- **AI interference identification**

### Action-style device operations

These are implemented as trigger-style preferences:

- **Start target distance tracking**
- **Start spatial learning**
- **Restart device**

After using one of these, it is usually a good idea to toggle it back off so it can be triggered again later.

### Temperature / humidity sampling and reporting

- **Sampling mode**
  - Off
  - Low
  - Medium
  - High
  - Custom
- **Sampling period**
- **Temperature reporting interval**
- **Temperature reporting threshold**
- **Temperature reporting mode**
- **Humidity reporting interval**
- **Humidity reporting threshold**
- **Humidity reporting mode**

### Light sampling and reporting

- **Light sampling mode**
  - Off
  - Low
  - Medium
  - High
  - Custom
- **Light sampling period**
- **Light reporting interval**
- **Light reporting threshold**
- **Light reporting mode**

### Detection range control

The driver supports two ways to tune the effective detection range:

- a **raw 24-bit detection range mask**
- six coarse 1-meter band toggles:
  - 0–1 m
  - 1–2 m
  - 2–3 m
  - 3–4 m
  - 4–5 m
  - 5–6 m

This makes the driver useful both for normal users and for advanced users who want to work directly with the device's internal range mask.

## How the driver works

Internally, the driver combines standard Zigbee handling with Aqara-specific logic.

### Standard Zigbee clusters

The driver binds and configures reporting for:

- `TemperatureMeasurement`
- `RelativeHumidity`
- `IlluminanceMeasurement`

These values are emitted to normal SmartThings capabilities.

### Aqara manufacturer-specific cluster

For the advanced FP300 functions, the driver talks to Aqara cluster:

- **Cluster:** `0xFCC0`
- **Manufacturer code:** `0x115F`

This is where the device exposes settings such as:

- presence mode
- motion sensitivity
- PIR interval
- absence delay
- AI features
- target distance
- detection range
- sampling/reporting configuration
- spatial learning
- restart action

### Separate presence and motion behavior

A key design choice in this driver is that it keeps:

- **presence** = general occupancy / stationary presence
- **motion** = PIR activity

separate from each other.

That makes the FP300 much more useful in SmartThings automations, because you can use the right signal for the right purpose:

- use **presence** when you want the room to stay occupied even if someone sits still
- use **motion** when you want fast PIR-like triggers

### Write verification

When preferences are changed, the driver does more than simply send writes once and hope for the best.

It uses a verification flow that:

1. sends the manufacturer-specific write
2. records the expected value
3. schedules a readback
4. logs verification success or timeout

That is a thoughtful reliability feature and especially useful on devices with a large number of vendor-specific attributes.

### Refresh behavior

The `Refresh` command reads:

- standard temperature / humidity / illuminance values
- selected Aqara-specific values such as battery, presence, PIR motion, target distance, detection range, and LED schedule raw data

## Battery handling

Battery handling is slightly more sophisticated than in many simple drivers.

The driver can process battery information from:

- the explicit Aqara battery voltage attribute
- Aqara's attribute report payload

When only millivolts are available, the driver converts voltage to percentage using a defined curve and clamps the result to 0–100%.

## What is special about the target distance capability?

The FP300 can report the current tracked target distance, and this driver exposes it through the custom capability:

```text
oceancircle09600.aqaratargetdistance
```

The raw value is converted to **meters** before being emitted.

That gives SmartThings users access to one of the FP300's more interesting mmWave-related data points, something generic integrations usually do not expose cleanly.

## Notes and caveats

### Zigbee mode only

This package is for the **Zigbee** version of the device behavior. The FP300 also supports Thread / Matter, but that is outside the scope of this driver.

### SmartThings UI depends on the profile

The profile included with this package exposes a large number of advanced preferences, but not every internal code path is necessarily user-visible in the app.

### Custom capability required

The target-distance feature depends on the custom capability:

```text
oceancircle09600.aqaratargetdistance
```

If your environment does not include that capability properly, the rest of the driver can still function, but target-distance presentation may be limited.

### Advanced tuning can affect battery life

Higher sampling frequency, shorter intervals, and aggressive detection settings can improve responsiveness but may reduce battery life.

### Remove and re-add may be necessary

If the device was first paired with another driver, SmartThings may not always automatically rebuild the device presentation the way you expect. In that case, re-pairing is often the cleanest solution.

## Developer notes

A few implementation details stand out when reviewing the code:

- the driver uses **debounced** `infoChanged` processing before applying preference updates
- it persists internal fields for **detection range mask**, **raw range bytes**, **target distance**, and related verification state
- it forces Aqara's **prevent-leave** attribute during configuration
- it supports both direct attribute reads and Aqara packed attribute-report parsing

One additional detail worth noting: the Lua source contains logic for **LED schedule / night LED handling**, but the included profile does not currently expose matching user-facing preferences for all of that functionality. In other words, some groundwork is already present in code for future extension.

## Suggested automation ideas

Once the driver is installed, the FP300 becomes much more useful in SmartThings. A few good examples:

- turn lights on when **motion** becomes active
- keep lights on while **presence** remains present, even without motion
- start ventilation when **humidity** rises above a threshold
- adjust blinds or lamps using **illuminance**
- use **temperature** for comfort automations
- monitor **target distance** for experiments, diagnostics, or advanced automations

## References

- Aqara FP300 product page:
  - https://www.aqara.com/eu/product/presence-multi-sensor-fp300/
- SmartThings Edge driver structure:
  - https://developer.smartthings.com/docs/devices/hub-connected/driver-components-and-structure/
- SmartThings shared channel installation:
  - https://developer.smartthings.com/docs/devices/hub-connected/enroll-in-a-shared-channel
- SmartThings driver channels:
  - https://developer.smartthings.com/docs/devices/hub-connected/driver-channels/

## Disclaimer

This is a **community driver**. It is not an official Aqara or Samsung / SmartThings driver.

Use it at your own risk, and expect that device firmware changes or SmartThings platform changes may require future updates.
