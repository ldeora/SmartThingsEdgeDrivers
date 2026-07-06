# Davis AirLink SmartThings Edge Driver

SmartThings Edge LAN driver for the Davis AirLink air quality sensor.

The driver uses the AirLink's local LAN API. No WeatherLink cloud account, API key, or internet connection is required for normal operation after the AirLink has joined the local network.

## Supported devices

- Davis AirLink 7210
- Davis AirLink 7210EU
- Davis AirLink 7210UK
- Davis AirLink 7210USB

The driver is intended for AirLink devices that expose the local `/v1/current_conditions` API and advertise the `_airlink._tcp` mDNS service.

## Features

- LAN discovery via mDNS/DNS-SD service `_airlink._tcp`
- SmartThings LAN pre-scan discovery through `search-parameters.yml`
- Local HTTP polling of `/v1/current_conditions`
- Stable SmartThings device network ID based on the AirLink `did` serial number
- Temperature and humidity reporting
- PM1.0, PM2.5, and PM10 reporting
- PM-based SmartThings health-concern categories
- Manual refresh command
- Configurable polling interval
- Optional static host/IP override for already-created devices
- Basic offline handling after repeated poll failures
- Rediscovery after repeated failures when no static host override is configured
- Optional debug logging

## SmartThings capabilities

- `temperatureMeasurement`
- `relativeHumidityMeasurement`
- `veryFineDustSensor` — PM1.0
- `veryFineDustHealthConcern`
- `fineDustSensor` — PM2.5
- `fineDustHealthConcern`
- `dustSensor` — PM10
- `dustHealthConcern`
- `airQualityHealthConcern`
- `refresh`

PM values are emitted as integer `μg/m^3` values because the SmartThings dust capabilities use positive integer attributes.

## AQI and health-concern handling

The Davis local API does not provide a numeric AQI value. This driver therefore does not emit a numeric `airQualitySensor.airQuality` value and does not claim to implement US AQI, CAQI, or another national AQI scale.

Instead, the driver emits SmartThings health-concern categories derived from particulate matter values:

- PM2.5 → `fineDustHealthConcern`
- PM10 → `dustHealthConcern`
- PM1.0 → `veryFineDustHealthConcern` using the same conservative category scale as PM2.5
- Worst of PM2.5 and PM10 → `airQualityHealthConcern`

By default, health-concern calculation uses AirLink NowCast values when available and sufficiently complete, then falls back to 1-hour values, then to one-minute values. A preference can switch the calculation to one-minute values directly.

## Preferences

- **Poll interval**: 60–3600 seconds. AirLink updates once per minute, so shorter intervals are intentionally not allowed.
- **Health concern basis**: NowCast preferred or one-minute average.
- **Static host or IP override**: optional fallback hostname or IP address for an already-created device. Leave empty to use mDNS-discovered addressing. The input is forgiving of plain host/IP, `host:port`, bracketed IPv6, or pasted `http://...` URLs.
- **Debug logging**: enables compact poll diagnostics in hub logs.

## Installation / packaging

Package the driver from the repository root or from the parent directory:

```bash
smartthings edge:drivers:package davis-airlink
```

Or from inside this directory:

```bash
smartthings edge:drivers:package .
```

Then publish and install the driver through the usual SmartThings Edge channel workflow.

## Pairing / discovery

1. Install the driver on the SmartThings hub.
2. Make sure the AirLink and hub are on the same LAN/VLAN.
3. Make sure mDNS/Bonjour/Zeroconf traffic is not blocked.
4. In the SmartThings app, use **Add device → Scan nearby**.
5. Wait for a device named after the AirLink's WeatherLink name, or `Davis AirLink`.
6. Open the device and verify temperature, humidity, PM1.0, PM2.5, PM10, and health-concern values.

## Troubleshooting

### Device is not discovered

Check:

- AirLink is powered and connected to Wi-Fi.
- Hub and AirLink are on the same LAN/VLAN.
- mDNS/Bonjour/Zeroconf is not blocked by the router/firewall.
- Guest Wi-Fi isolation is disabled.

On a Linux/macOS machine in the same network, test discovery with one of these commands:

```bash
avahi-browse -rt _airlink._tcp
```

```bash
dns-sd -B _airlink._tcp local
```

### Local API test

From a computer on the same LAN:

```bash
curl http://airlink-XXXXXX.local/v1/current_conditions
```

or:

```bash
curl http://<airlink-ip>/v1/current_conditions
```

### Useful SmartThings log command

```bash
smartthings edge:drivers:logcat -a
```

Enable the **Debug logging** preference if detailed poll lines are needed.

## Notes

This is a LAN/local-API driver. It does not use the WeatherLink cloud service and does not require a WeatherLink API key.

The AirLink updates its local readings roughly once per minute. Long-term and NowCast values may be incomplete shortly after an AirLink restart; this is expected.
