# SmartThings Edge Driver for IKEA VINDSTYRKA Air Quality Sensor

## Overview

This project provides a SmartThings Edge Driver for the IKEA VINDSTYRKA air quality sensor. The VINDSTYRKA sensor monitors several environmental parameters, including:

- **Temperature**
- **Relative Humidity**
- **Particulate Matter (PM 2.5)**
- **Total Volatile Organic Compounds (TVOC)**
- **Air Quality Health Concern**

The driver integrates the VINDSTYRKA sensor with the SmartThings ecosystem, enabling real-time monitoring and automation based on air quality and environmental conditions.

---

## Features

### Supported Capabilities:
- **Temperature Measurement**: Displays current temperature.
- **Humidity Measurement**: Displays relative humidity.
- **Fine Dust Sensor**: Monitors PM 2.5 concentration in µg/m³.
- **TVOC Measurement**: Monitors Total Volatile Organic Compounds (TVOC) in ppm.
- **Air Quality Health Concern**: Categorizes air quality into levels (e.g., "Good," "Moderate," "Unhealthy").
- **Refresh**: Allows manual refresh of sensor data.

### Key Functionalities:
- **Custom Reporting Intervals**: Configure reporting intervals for temperature, humidity, PM 2.5, and TVOC measurements (1–600 seconds, default: 30 seconds).
- **Real-Time Data Conversion**: Automatically converts raw sensor data into human-readable formats for SmartThings.
- **Air Quality Categorization**: Evaluates PM 2.5 data to determine health concern levels.
- **Automation Integration**: Supports automations based on sensor readings (e.g., adjust air purifiers based on air quality).

---

## Installation

Click on the following link and follow the instructions:

https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20

---

## Configuration

### Preferences:
The driver provides customizable settings for data reporting intervals:
- **Temperature Reporting Interval**: Default is 30 seconds.
- **Humidity Reporting Interval**: Default is 30 seconds.
- **PM 2.5 Reporting Interval**: Default is 30 seconds.
- **TVOC Reporting Interval**: Default is 30 seconds.

Adjust these intervals through the SmartThings app's device preferences.

---

## Developer Notes

### Code Structure:
- **`init.lua`**: Main logic of the driver, including event handlers and Zigbee attribute management.
- **`humidity-temp-dust-tvoc.yml`**: Device profile definition with supported capabilities and UI configuration.
- **`config.yml`**: Driver metadata and packaging information.
- **`fingerprints.yml`**: Zigbee device identification.

### Supported Zigbee Clusters:
- Temperature Measurement
- Relative Humidity Measurement
- PM 2.5 Concentration Measurement
- TVOC Measurement (manufacturer specific)

### Health Categorization:
PM 2.5 readings are categorized as:
- Good: 0–15 µg/m³
- Moderate: 15–35 µg/m³
- Slightly Unhealthy: 35–55 µg/m³
- Unhealthy: 55–150 µg/m³
- Very Unhealthy: 150–250 µg/m³
- Hazardous: >250 µg/m³

---

## Issues and Contributions

If you encounter any issues or want to contribute to this project:
1. Open an issue on GitHub.
2. Submit a pull request with your changes.

---

## License

This project is licensed under the [MIT License](LICENSE).
