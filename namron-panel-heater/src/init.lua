-- Namron 540139X Zigbee Panel Heater SmartThings Edge Driver
-- v0.1.4
--
-- Supported models: 5401392/3/4/5/6/7/8/9
-- Manufacturer: NAMRON AS
--
-- Design goal for v0.1.x:
--   * Reliable thermostat + metering support first.
--   * Confirmed proprietary Sunricher/Namron attributes as preferences.
--   * No experimental local scheduler/auto-program support yet.

local log = require "log"
local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"
local device_management = require "st.zigbee.device_management"
local cluster_base = require "st.zigbee.cluster_base"
local data_types = require "st.zigbee.data_types"

local DRIVER_NAME = "namron-panel-heater"
local DRIVER_VERSION = "0.1.4"

-- Cluster IDs
local BASIC_CLUSTER_ID = 0x0000
local IDENTIFY_CLUSTER_ID = 0x0003
local ALARMS_CLUSTER_ID = 0x0009
local TIME_CLUSTER_ID = 0x000A
local THERMOSTAT_CLUSTER_ID = 0x0201
local THERMOSTAT_UI_CLUSTER_ID = 0x0204
local SIMPLE_METERING_CLUSTER_ID = 0x0702
local ELECTRICAL_MEASUREMENT_CLUSTER_ID = 0x0B04

-- Standard Thermostat attributes
local ATTR_LOCAL_TEMPERATURE = 0x0000
local ATTR_LOCAL_TEMPERATURE_CALIBRATION = 0x0010
local ATTR_OCCUPIED_HEATING_SETPOINT = 0x0012
local ATTR_SYSTEM_MODE = 0x001C
local ATTR_THERMOSTAT_RUNNING_STATE = 0x0029

-- Thermostat UI attributes
local ATTR_KEYPAD_LOCKOUT = 0x0001

-- Simple Metering attributes
local ATTR_CURRENT_SUMMATION_DELIVERED = 0x0000
local ATTR_METERING_MULTIPLIER = 0x0301
local ATTR_METERING_DIVISOR = 0x0302

-- Electrical Measurement attributes
local ATTR_RMS_VOLTAGE = 0x0505
local ATTR_RMS_CURRENT = 0x0508
local ATTR_ACTIVE_POWER = 0x050B
local ATTR_AC_VOLTAGE_MULTIPLIER = 0x0600
local ATTR_AC_VOLTAGE_DIVISOR = 0x0601
local ATTR_AC_CURRENT_MULTIPLIER = 0x0602
local ATTR_AC_CURRENT_DIVISOR = 0x0603
local ATTR_AC_POWER_MULTIPLIER = 0x0604
local ATTR_AC_POWER_DIVISOR = 0x0605

-- Manufacturer-specific Thermostat attributes
local MFG_CODE = 0x1224 -- Shenzhen Sunricher Technology Ltd.
local ATTR_DISPLAY_BRIGHTNESS = 0x1000
local ATTR_DISPLAY_AUTO_OFF = 0x1001
local ATTR_POWER_UP_STATUS = 0x1004
local ATTR_WINDOW_DETECTION = 0x1009 -- windowOpenCheck2 in zigbee-herdsman-converters; non-PRO enable flag
local ATTR_HYSTERESIS = 0x100A -- Zigbee2MQTT name typo: hysterersis
local ATTR_WINDOW_OPEN = 0x100B

-- Raw ZCL data type IDs. Keeping these as plain constants avoids depending on
-- optional data_types aliases that may differ between hub firmware/library builds.
local DATA_TYPE_UINT8_ID = 0x20
local DATA_TYPE_UINT16_ID = 0x21
local DATA_TYPE_UINT48_ID = 0x25
local DATA_TYPE_INT16_ID = 0x29
local DATA_TYPE_ENUM8_ID = 0x30
local DATA_TYPE_BITMAP16_ID = 0x19

-- Stored multiplier/divisor fields. Defaults match observed ZHA reports for this device family.
local F_VOLTAGE_MULTIPLIER = "voltage_multiplier"
local F_VOLTAGE_DIVISOR = "voltage_divisor"
local F_CURRENT_MULTIPLIER = "current_multiplier"
local F_CURRENT_DIVISOR = "current_divisor"
local F_POWER_MULTIPLIER = "power_multiplier"
local F_POWER_DIVISOR = "power_divisor"
local F_ENERGY_MULTIPLIER = "energy_multiplier"
local F_ENERGY_DIVISOR = "energy_divisor"
local F_RAW_TEMP = "raw_local_temperature"
local F_RAW_SETPOINT = "raw_heating_setpoint"
local F_PREFS_SEEN = "prefs_seen"
local F_INFO_CHANGED_GENERATION = "info_changed_generation"

local INFO_CHANGED_DEBOUNCE_SECONDS = 2

local ThermostatMode = capabilities.thermostatMode
local ThermostatHeatingSetpoint = capabilities.thermostatHeatingSetpoint
local ThermostatOperatingState = capabilities.thermostatOperatingState
local TemperatureMeasurement = capabilities.temperatureMeasurement
local Switch = capabilities.switch
local PowerMeter = capabilities.powerMeter
local EnergyMeter = capabilities.energyMeter
local VoltageMeasurement = capabilities.voltageMeasurement
local CurrentMeasurement = capabilities.currentMeasurement
local ContactSensor = capabilities.contactSensor

local SUPPORTED_THERMOSTAT_MODES = {
  ThermostatMode.thermostatMode.off.NAME,
  ThermostatMode.thermostatMode.heat.NAME,
}

local function device_name(device)
  return (device and (device.label or device.id)) or "unknown"
end

local function debug_log(device, message, ...)
  if not (device and device.preferences and device.preferences.debugLogging) then return end
  local ok, formatted = pcall(string.format, "[Namron Panel Heater][%s] " .. tostring(message), device_name(device), ...)
  if ok then
    log.info(formatted)
  else
    log.info("[Namron Panel Heater] " .. tostring(message))
  end
end

local function warn_log(device, message, ...)
  local ok, formatted = pcall(string.format, "[Namron Panel Heater][%s] " .. tostring(message), device_name(device), ...)
  if ok then
    log.warn(formatted)
  else
    log.warn("[Namron Panel Heater] " .. tostring(message))
  end
end

local function guarded(name, fn)
  return function(driver, device, ...)
    local ok, err = pcall(fn, driver, device, ...)
    if not ok then
      warn_log(device, "%s failed: %s", tostring(name), tostring(err))
    end
  end
end

local function safe_send(device, message, label)
  if message == nil then return false end
  local ok, err = pcall(function()
    device:send(message)
  end)
  if not ok then
    warn_log(device, "send failed for %s: %s", tostring(label or "message"), tostring(err))
    return false
  end
  return true
end

local function safe_build_send(device, label, builder)
  local ok, message_or_err = pcall(builder)
  if not ok then
    warn_log(device, "message build failed for %s: %s", tostring(label or "message"), tostring(message_or_err))
    return false
  end
  return safe_send(device, message_or_err, label)
end

local function safe_delay(device, seconds, label, fn)
  if not (device and device.thread and device.thread.call_with_delay) then return false end
  local ok, err = pcall(function()
    device.thread:call_with_delay(seconds, function()
      local inner_ok, inner_err = pcall(fn)
      if not inner_ok then
        warn_log(device, "delayed task failed for %s: %s", tostring(label or "task"), tostring(inner_err))
      end
    end)
  end)
  if not ok then
    warn_log(device, "failed to schedule %s: %s", tostring(label or "task"), tostring(err))
    return false
  end
  return true
end

local function numeric_value(value)
  if value == nil then return nil end
  if type(value) == "number" then return value end
  if type(value) == "table" and value.value ~= nil then return value.value end
  local ok, n = pcall(tonumber, value)
  if ok then return n end
  return nil
end

local function clamp(value, minimum, maximum)
  if value < minimum then return minimum end
  if value > maximum then return maximum end
  return value
end

local function round_to(value, decimals)
  local mult = 10 ^ decimals
  return math.floor((value * mult) + 0.5) / mult
end

local function round_int(value)
  if value >= 0 then
    return math.floor(value + 0.5)
  end
  return math.ceil(value - 0.5)
end

local function f_to_c(value)
  return (value - 32) * 5 / 9
end

local function signed8(raw)
  if raw == nil then return nil end
  if raw > 0x7F then return raw - 0x100 end
  return raw
end

local function signed16(raw)
  if raw == nil then return nil end
  if raw > 0x7FFF then return raw - 0x10000 end
  return raw
end

local function attr_id(attr_id)
  return data_types.validate_or_build_type(attr_id, data_types.AttributeId, "attr_id")
end

local function add_mfg_header(message, mfg_code)
  if mfg_code ~= nil then
    message.body.zcl_header.frame_ctrl:set_mfg_specific()
    message.body.zcl_header.mfg_code = data_types.validate_or_build_type(mfg_code, data_types.Uint16, "mfg_code")
  end
  return message
end

local function build_read_attr(device, cluster_id, attribute_id, mfg_code)
  local message = cluster_base.read_attribute(device, data_types.ClusterId(cluster_id), attr_id(attribute_id))
  return add_mfg_header(message, mfg_code)
end

local function build_write_attr(device, cluster_id, attribute_id, data_type, value, mfg_code)
  local data = data_types.validate_or_build_type(value, data_type)
  local message = cluster_base.write_attribute(device, data_types.ClusterId(cluster_id), attr_id(attribute_id), data)
  return add_mfg_header(message, mfg_code)
end

local function build_configure_reporting(device, cluster_id, attribute_id, data_type_id, min_interval, max_interval, reportable_change, mfg_code)
  local message = cluster_base.configure_reporting(
    device,
    data_types.ClusterId(cluster_id),
    attr_id(attribute_id),
    data_type_id,
    min_interval,
    max_interval,
    reportable_change
  )
  return add_mfg_header(message, mfg_code)
end

local function read_attr(device, cluster_id, attribute_id, mfg_code, label)
  return safe_build_send(device, label or string.format("read 0x%04X/0x%04X", cluster_id, attribute_id), function()
    return build_read_attr(device, cluster_id, attribute_id, mfg_code)
  end)
end

local function write_attr(device, cluster_id, attribute_id, data_type, value, mfg_code, label)
  return safe_build_send(device, label or string.format("write 0x%04X/0x%04X", cluster_id, attribute_id), function()
    return build_write_attr(device, cluster_id, attribute_id, data_type, value, mfg_code)
  end)
end

local function configure_reporting(device, cluster_id, attribute_id, data_type_id, min_interval, max_interval, reportable_change, mfg_code, label)
  debug_log(device, "configure reporting %s: cluster=0x%04X attr=0x%04X min=%s max=%s change=%s type=0x%02X mfg=%s",
    tostring(label or ""), cluster_id, attribute_id, tostring(min_interval), tostring(max_interval), tostring(reportable_change), data_type_id, mfg_code and string.format("0x%04X", mfg_code) or "none")
  return safe_build_send(device, label or string.format("configure reporting 0x%04X/0x%04X", cluster_id, attribute_id), function()
    return build_configure_reporting(device, cluster_id, attribute_id, data_type_id, min_interval, max_interval, reportable_change, mfg_code)
  end)
end

local function read_mfr_attr(device, attribute_id)
  read_attr(device, THERMOSTAT_CLUSTER_ID, attribute_id, MFG_CODE, string.format("read mfg attr 0x%04X", attribute_id))
end

local function write_mfr_attr(device, attribute_id, data_type, value, label)
  debug_log(device, "write mfg attr 0x%04X = %s", attribute_id, tostring(value))
  write_attr(device, THERMOSTAT_CLUSTER_ID, attribute_id, data_type, value, MFG_CODE, label or string.format("write mfg attr 0x%04X", attribute_id))
end

local function schedule_read(device, cluster_id, attribute_id, mfg_code, delay)
  safe_delay(device, delay or 1, string.format("readback 0x%04X/0x%04X", cluster_id, attribute_id), function()
    read_attr(device, cluster_id, attribute_id, mfg_code)
  end)
end

local function init_scaling_defaults(device)
  if device:get_field(F_VOLTAGE_MULTIPLIER) == nil then device:set_field(F_VOLTAGE_MULTIPLIER, 1, { persist = true }) end
  if device:get_field(F_VOLTAGE_DIVISOR) == nil then device:set_field(F_VOLTAGE_DIVISOR, 10, { persist = true }) end
  if device:get_field(F_CURRENT_MULTIPLIER) == nil then device:set_field(F_CURRENT_MULTIPLIER, 1, { persist = true }) end
  if device:get_field(F_CURRENT_DIVISOR) == nil then device:set_field(F_CURRENT_DIVISOR, 1000, { persist = true }) end
  if device:get_field(F_POWER_MULTIPLIER) == nil then device:set_field(F_POWER_MULTIPLIER, 1, { persist = true }) end
  if device:get_field(F_POWER_DIVISOR) == nil then device:set_field(F_POWER_DIVISOR, 10, { persist = true }) end
  if device:get_field(F_ENERGY_MULTIPLIER) == nil then device:set_field(F_ENERGY_MULTIPLIER, 1, { persist = true }) end
  if device:get_field(F_ENERGY_DIVISOR) == nil then device:set_field(F_ENERGY_DIVISOR, 10, { persist = true }) end
end

local function scaled_value(device, raw, multiplier_field, divisor_field, decimals)
  local multiplier = device:get_field(multiplier_field) or 1
  local divisor = device:get_field(divisor_field) or 1
  if divisor == 0 then divisor = 1 end
  return round_to((raw * multiplier) / divisor, decimals or 2)
end

local function emit_mode(device, mode)
  if mode == "heat" then
    device:emit_event(ThermostatMode.thermostatMode.heat())
    device:emit_event(Switch.switch.on())
  else
    device:emit_event(ThermostatMode.thermostatMode.off())
    device:emit_event(Switch.switch.off())
    device:emit_event(ThermostatOperatingState.thermostatOperatingState.idle())
  end
end

local function maybe_update_operating_state_from_temp(device)
  local raw_temp = device:get_field(F_RAW_TEMP)
  local raw_setpoint = device:get_field(F_RAW_SETPOINT)
  local mode = device:get_latest_state("main", ThermostatMode.ID, ThermostatMode.thermostatMode.NAME)

  if mode == ThermostatMode.thermostatMode.off.NAME then
    device:emit_event(ThermostatOperatingState.thermostatOperatingState.idle())
    return
  end

  -- Fallback only. The device also reports ThermostatRunningState; that report wins when available.
  if raw_temp ~= nil and raw_setpoint ~= nil then
    if raw_temp < raw_setpoint then
      device:emit_event(ThermostatOperatingState.thermostatOperatingState.heating())
    else
      device:emit_event(ThermostatOperatingState.thermostatOperatingState.idle())
    end
  end
end

local function thermostat_temperature_handler(_, device, value, _)
  local raw = signed16(numeric_value(value))
  if raw == nil or raw == -32768 or raw == 0x8000 then return end
  device:set_field(F_RAW_TEMP, raw, { persist = false })
  device:emit_event(TemperatureMeasurement.temperature({ value = round_to(raw / 100.0, 2), unit = "C" }))
  debug_log(device, "local temperature %.2f C", raw / 100.0)
  maybe_update_operating_state_from_temp(device)
end

local function heating_setpoint_handler(_, device, value, _)
  local raw = signed16(numeric_value(value))
  if raw == nil or raw == -32768 or raw == 0x8000 then return end
  device:set_field(F_RAW_SETPOINT, raw, { persist = false })
  device:emit_event(ThermostatHeatingSetpoint.heatingSetpoint({ value = round_to(raw / 100.0, 2), unit = "C" }))
  debug_log(device, "heating setpoint %.2f C", raw / 100.0)
  maybe_update_operating_state_from_temp(device)
end

local function system_mode_handler(_, device, value, _)
  local raw = numeric_value(value)
  debug_log(device, "systemMode raw=%s", tostring(raw))
  if raw == 0x00 then
    emit_mode(device, "off")
  elseif raw == 0x04 then
    emit_mode(device, "heat")
  else
    warn_log(device, "unhandled systemMode value: %s", tostring(raw))
  end
end

local function running_state_handler(_, device, value, _)
  local raw = numeric_value(value) or 0
  local heat_on = (raw & 0x0001) ~= 0
  if heat_on then
    device:emit_event(ThermostatOperatingState.thermostatOperatingState.heating())
  else
    device:emit_event(ThermostatOperatingState.thermostatOperatingState.idle())
  end
  debug_log(device, "runningState raw=0x%04X", raw)
end

local function local_temperature_calibration_handler(_, device, value, _)
  local raw = signed8(numeric_value(value))
  if raw == nil then return end
  debug_log(device, "local temperature calibration %.1f C", raw / 10.0)
end

local function keypad_lockout_handler(_, device, value, _)
  local raw = numeric_value(value) or 0
  device:set_field("child_lock_state", raw == 0 and "unlocked" or "locked", { persist = true })
  debug_log(device, "child lock %s", raw == 0 and "unlocked" or "locked")
end

local function simple_metering_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw == nil then return end
  local energy = scaled_value(device, raw, F_ENERGY_MULTIPLIER, F_ENERGY_DIVISOR, 3)
  device:emit_event(EnergyMeter.energy({ value = energy, unit = "kWh" }))
  debug_log(device, "energy raw=%s scaled=%.3f kWh", tostring(raw), energy)
end

local function metering_multiplier_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil and raw > 0 then device:set_field(F_ENERGY_MULTIPLIER, raw, { persist = true }) end
end

local function metering_divisor_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil and raw > 0 then device:set_field(F_ENERGY_DIVISOR, raw, { persist = true }) end
end

local function rms_voltage_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw == nil then return end
  local voltage = scaled_value(device, raw, F_VOLTAGE_MULTIPLIER, F_VOLTAGE_DIVISOR, 1)
  device:emit_event(VoltageMeasurement.voltage({ value = voltage, unit = "V" }))
  debug_log(device, "voltage raw=%s scaled=%.1f V", tostring(raw), voltage)
end

local function rms_current_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw == nil then return end
  local current = scaled_value(device, raw, F_CURRENT_MULTIPLIER, F_CURRENT_DIVISOR, 3)
  device:emit_event(CurrentMeasurement.current({ value = current, unit = "A" }))
  debug_log(device, "current raw=%s scaled=%.3f A", tostring(raw), current)
end

local function active_power_handler(_, device, value, _)
  local raw = signed16(numeric_value(value))
  if raw == nil then return end
  local power = scaled_value(device, raw, F_POWER_MULTIPLIER, F_POWER_DIVISOR, 1)
  device:emit_event(PowerMeter.power({ value = power, unit = "W" }))
  debug_log(device, "power raw=%s scaled=%.1f W", tostring(raw), power)
end

local function set_multiplier_field(field)
  return function(_, device, value, _)
    local raw = numeric_value(value)
    if raw ~= nil and raw > 0 then device:set_field(field, raw, { persist = true }) end
  end
end

local function display_brightness_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil then
    device:set_field("display_brightness", raw, { persist = true })
    debug_log(device, "display brightness %s", tostring(raw))
  end
end

local function display_auto_off_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil then
    device:set_field("display_auto_off", raw == 1 and "activated" or "deactivated", { persist = true })
    debug_log(device, "display auto off %s", raw == 1 and "activated" or "deactivated")
  end
end

local function power_up_status_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil then
    device:set_field("power_up_status", raw == 1 and "last_state" or "manual", { persist = true })
    debug_log(device, "power-up status %s", raw == 1 and "last_state" or "manual")
  end
end

local function window_detection_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil then
    device:set_field("window_detection", raw == 1 and "enabled" or "disabled", { persist = true })
    debug_log(device, "window detection %s", raw == 1 and "enabled" or "disabled")
  end
end

local function hysteresis_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw ~= nil then
    device:set_field("hysteresis", raw / 10.0, { persist = true })
    debug_log(device, "hysteresis %.1f C", raw / 10.0)
  end
end

local function window_open_handler(_, device, value, _)
  local raw = numeric_value(value)
  if raw == nil then return end
  if raw == 1 then
    device:emit_event(ContactSensor.contact.open())
  else
    device:emit_event(ContactSensor.contact.closed())
  end
  debug_log(device, "window open raw=%s", tostring(raw))
end

local function set_heating_setpoint(_, device, command)
  local value = tonumber(command.args.setpoint)
  if value == nil then return end

  -- The app can occasionally send Fahrenheit-like values depending on locale. Treat >= 40 as Fahrenheit.
  if value >= 40 then value = f_to_c(value) end
  value = clamp(value, 5.0, 35.0)

  local raw = round_int(value * 100)
  write_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_OCCUPIED_HEATING_SETPOINT, data_types.Int16, raw, nil, "write heating setpoint")
  device:emit_event(ThermostatHeatingSetpoint.heatingSetpoint({ value = round_to(raw / 100.0, 2), unit = "C" }))
  schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_OCCUPIED_HEATING_SETPOINT, nil, 1)
  schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_THERMOSTAT_RUNNING_STATE, nil, 2)
end

local function set_thermostat_mode_value(_, device, mode)
  if mode == ThermostatMode.thermostatMode.heat.NAME then
    write_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_SYSTEM_MODE, data_types.Enum8, 0x04, nil, "write systemMode heat")
    emit_mode(device, "heat")
  elseif mode == ThermostatMode.thermostatMode.off.NAME then
    write_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_SYSTEM_MODE, data_types.Enum8, 0x00, nil, "write systemMode off")
    emit_mode(device, "off")
  else
    warn_log(device, "unsupported thermostat mode command: %s", tostring(mode))
    local current = device:get_latest_state("main", ThermostatMode.ID, ThermostatMode.thermostatMode.NAME) or ThermostatMode.thermostatMode.off.NAME
    device:emit_event(ThermostatMode.thermostatMode(current))
    return
  end

  schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_SYSTEM_MODE, nil, 1)
  schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_THERMOSTAT_RUNNING_STATE, nil, 2)
end

local function set_thermostat_mode(driver, device, command)
  return set_thermostat_mode_value(driver, device, command.args.mode)
end

local function thermostat_mode_setter(mode_name)
  return function(driver, device, _)
    return set_thermostat_mode_value(driver, device, mode_name)
  end
end

local function switch_on(driver, device, _)
  return set_thermostat_mode_value(driver, device, ThermostatMode.thermostatMode.heat.NAME)
end

local function switch_off(driver, device, _)
  return set_thermostat_mode_value(driver, device, ThermostatMode.thermostatMode.off.NAME)
end

local function read_all_values(_, device)
  -- Standard thermostat
  read_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_LOCAL_TEMPERATURE)
  read_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_LOCAL_TEMPERATURE_CALIBRATION)
  read_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_OCCUPIED_HEATING_SETPOINT)
  read_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_SYSTEM_MODE)
  read_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_THERMOSTAT_RUNNING_STATE)

  -- UI / child lock
  read_attr(device, THERMOSTAT_UI_CLUSTER_ID, ATTR_KEYPAD_LOCKOUT)

  -- Metering and electrical measurement scaling + values
  read_attr(device, SIMPLE_METERING_CLUSTER_ID, ATTR_METERING_MULTIPLIER)
  read_attr(device, SIMPLE_METERING_CLUSTER_ID, ATTR_METERING_DIVISOR)
  read_attr(device, SIMPLE_METERING_CLUSTER_ID, ATTR_CURRENT_SUMMATION_DELIVERED)

  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_AC_VOLTAGE_MULTIPLIER)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_AC_VOLTAGE_DIVISOR)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_AC_CURRENT_MULTIPLIER)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_AC_CURRENT_DIVISOR)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_AC_POWER_MULTIPLIER)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_AC_POWER_DIVISOR)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_RMS_VOLTAGE)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_RMS_CURRENT)
  read_attr(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_ACTIVE_POWER)

  -- Manufacturer-specific panel heater settings/state
  read_mfr_attr(device, ATTR_DISPLAY_BRIGHTNESS)
  read_mfr_attr(device, ATTR_DISPLAY_AUTO_OFF)
  read_mfr_attr(device, ATTR_POWER_UP_STATUS)
  read_mfr_attr(device, ATTR_WINDOW_DETECTION)
  read_mfr_attr(device, ATTR_HYSTERESIS)
  read_mfr_attr(device, ATTR_WINDOW_OPEN)
end

local function refresh(driver, device, _)
  init_scaling_defaults(device)
  read_all_values(driver, device)
end

local function configure_device(driver, device)
  init_scaling_defaults(device)
  log.info(string.format("[Namron Panel Heater][%s] configuring %s", device_name(device), DRIVER_VERSION))

  local hub_eui = driver.environment_info and driver.environment_info.hub_zigbee_eui
  if hub_eui ~= nil then
    local bind_clusters = {
      BASIC_CLUSTER_ID,
      IDENTIFY_CLUSTER_ID,
      THERMOSTAT_CLUSTER_ID,
      SIMPLE_METERING_CLUSTER_ID,
      ELECTRICAL_MEASUREMENT_CLUSTER_ID,
      ALARMS_CLUSTER_ID,
      TIME_CLUSTER_ID,
      THERMOSTAT_UI_CLUSTER_ID,
    }

    for _, cluster_id in ipairs(bind_clusters) do
      safe_build_send(device, string.format("bind cluster 0x%04X", cluster_id), function()
        return device_management.build_bind_request(device, cluster_id, hub_eui)
      end)
    end
  else
    warn_log(device, "cannot bind clusters: hub Zigbee EUI missing")
  end

  -- Standard thermostat reporting. Local temperature is deliberately set to 0.5 C change to avoid report spam.
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_LOCAL_TEMPERATURE, DATA_TYPE_INT16_ID, 30, 300, 50, nil, "cfg localTemperature")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_OCCUPIED_HEATING_SETPOINT, DATA_TYPE_INT16_ID, 10, 300, 50, nil, "cfg heatingSetpoint")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_SYSTEM_MODE, DATA_TYPE_ENUM8_ID, 10, 300, nil, nil, "cfg systemMode")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_THERMOSTAT_RUNNING_STATE, DATA_TYPE_BITMAP16_ID, 10, 300, nil, nil, "cfg runningState")
  configure_reporting(device, THERMOSTAT_UI_CLUSTER_ID, ATTR_KEYPAD_LOCKOUT, DATA_TYPE_ENUM8_ID, 10, 3600, nil, nil, "cfg keypadLockout")

  -- Simple Metering / Electrical Measurement reporting. Matches Zigbee2MQTT strategy and observed scaling.
  configure_reporting(device, SIMPLE_METERING_CLUSTER_ID, ATTR_CURRENT_SUMMATION_DELIVERED, DATA_TYPE_UINT48_ID, 300, 3600, 1, nil, "cfg energy")
  configure_reporting(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_RMS_VOLTAGE, DATA_TYPE_UINT16_ID, 10, 300, 20, nil, "cfg voltage")
  configure_reporting(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_RMS_CURRENT, DATA_TYPE_UINT16_ID, 10, 300, 10, nil, "cfg current")
  configure_reporting(device, ELECTRICAL_MEASUREMENT_CLUSTER_ID, ATTR_ACTIVE_POWER, DATA_TYPE_INT16_ID, 10, 300, 15, nil, "cfg power")

  -- Manufacturer-specific settings. Manufacturer code in the ZCL frame is essential.
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_DISPLAY_BRIGHTNESS, DATA_TYPE_ENUM8_ID, 60, 3600, nil, MFG_CODE, "cfg display brightness")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_DISPLAY_AUTO_OFF, DATA_TYPE_ENUM8_ID, 60, 3600, nil, MFG_CODE, "cfg display auto-off")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_POWER_UP_STATUS, DATA_TYPE_ENUM8_ID, 60, 3600, nil, MFG_CODE, "cfg power-up status")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_WINDOW_DETECTION, DATA_TYPE_ENUM8_ID, 60, 3600, nil, MFG_CODE, "cfg window detection")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_HYSTERESIS, DATA_TYPE_UINT8_ID, 60, 3600, 1, MFG_CODE, "cfg hysteresis")
  configure_reporting(device, THERMOSTAT_CLUSTER_ID, ATTR_WINDOW_OPEN, DATA_TYPE_ENUM8_ID, 30, 3600, nil, MFG_CODE, "cfg window open")

  safe_delay(device, 3, "configure readback", function()
    read_all_values(driver, device)
    debug_log(device, "configuration readback requested")
  end)

  log.info(string.format("[Namron Panel Heater][%s] configuration commands queued; readback scheduled", device_name(device)))
end

local function device_added(_, device)
  init_scaling_defaults(device)
  device:emit_event(ThermostatMode.supportedThermostatModes(SUPPORTED_THERMOSTAT_MODES, { visibility = { displayed = false } }))
  device:emit_event(ThermostatMode.thermostatMode.off())
  device:emit_event(ThermostatOperatingState.thermostatOperatingState.idle())
  device:emit_event(Switch.switch.off())
  device:emit_event(ContactSensor.contact.closed())
end

local function device_init(_, device)
  init_scaling_defaults(device)
  debug_log(device, "init %s", DRIVER_VERSION)
end

local function changed_pref(device, old_prefs, name)
  local current = device.preferences and device.preferences[name]
  local old = old_prefs and old_prefs[name]
  return current ~= nil and old ~= nil and current ~= old
end

local function apply_preferences_now(_, device, old_prefs)
  -- Do not write profile defaults on the first infoChanged. This avoids resetting a tester's physical heater settings
  -- just because the driver was installed. Preferences are written only after a real user change.
  if not device:get_field(F_PREFS_SEEN) then
    device:set_field(F_PREFS_SEEN, true, { persist = true })
    debug_log(device, "first infoChanged seen; not writing defaults")
    return
  end

  if changed_pref(device, old_prefs, "localTempCalibration") then
    local value = tonumber(device.preferences.localTempCalibration)
    if value ~= nil then
      value = clamp(value, -3.0, 3.0)
      local raw = round_int(value * 10)
      write_attr(device, THERMOSTAT_CLUSTER_ID, ATTR_LOCAL_TEMPERATURE_CALIBRATION, data_types.Int8, raw, nil, "write temperature calibration")
      schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_LOCAL_TEMPERATURE_CALIBRATION, nil, 1)
    end
  end

  if changed_pref(device, old_prefs, "childLock") then
    local pref = device.preferences.childLock
    if pref == "locked" or pref == "unlocked" then
      write_attr(device, THERMOSTAT_UI_CLUSTER_ID, ATTR_KEYPAD_LOCKOUT, data_types.Enum8, pref == "locked" and 1 or 0, nil, "write child lock")
      schedule_read(device, THERMOSTAT_UI_CLUSTER_ID, ATTR_KEYPAD_LOCKOUT, nil, 1)
    end
  end

  if changed_pref(device, old_prefs, "hysteresis") then
    local pref = device.preferences.hysteresis
    if pref ~= nil and pref ~= "unchanged" then
      -- SmartThings preference option keys must match ^\w+$, so the profile
      -- uses h05..h20 instead of literal keys like "0.5".
      local hysteresis_values = {
        h05 = 0.5, h06 = 0.6, h07 = 0.7, h08 = 0.8, h09 = 0.9,
        h10 = 1.0, h11 = 1.1, h12 = 1.2, h13 = 1.3, h14 = 1.4,
        h15 = 1.5, h16 = 1.6, h17 = 1.7, h18 = 1.8, h19 = 1.9, h20 = 2.0,
      }
      local value = hysteresis_values[pref] or tonumber(pref) or 0.5
      value = clamp(value, 0.5, 2.0)
      debug_log(device, "writing hysteresis preference %s -> %.1f C (raw %d)", tostring(pref), value, round_int(value * 10))
      write_mfr_attr(device, ATTR_HYSTERESIS, data_types.Uint8, round_int(value * 10), "write hysteresis")
      schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_HYSTERESIS, MFG_CODE, 1)
    end
  end

  if changed_pref(device, old_prefs, "displayBrightness") then
    local pref = device.preferences.displayBrightness
    if pref ~= nil and pref ~= "unchanged" then
      local value = clamp(tonumber(pref) or 1, 1, 7)
      write_mfr_attr(device, ATTR_DISPLAY_BRIGHTNESS, data_types.Enum8, value, "write display brightness")
      schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_DISPLAY_BRIGHTNESS, MFG_CODE, 1)
    end
  end

  if changed_pref(device, old_prefs, "displayAutoOff") then
    local pref = device.preferences.displayAutoOff
    if pref == "activated" or pref == "deactivated" then
      write_mfr_attr(device, ATTR_DISPLAY_AUTO_OFF, data_types.Enum8, pref == "activated" and 1 or 0, "write display auto-off")
      schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_DISPLAY_AUTO_OFF, MFG_CODE, 1)
    end
  end

  if changed_pref(device, old_prefs, "powerUpStatus") then
    local pref = device.preferences.powerUpStatus
    if pref == "manual" or pref == "last_state" then
      write_mfr_attr(device, ATTR_POWER_UP_STATUS, data_types.Enum8, pref == "last_state" and 1 or 0, "write power-up status")
      schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_POWER_UP_STATUS, MFG_CODE, 1)
    end
  end

  if changed_pref(device, old_prefs, "windowDetection") then
    local pref = device.preferences.windowDetection
    if pref == "enabled" or pref == "disabled" then
      write_mfr_attr(device, ATTR_WINDOW_DETECTION, data_types.Enum8, pref == "enabled" and 1 or 0, "write window detection")
      schedule_read(device, THERMOSTAT_CLUSTER_ID, ATTR_WINDOW_DETECTION, MFG_CODE, 1)
    end
  end
end

local function apply_preferences(driver, device, _, args)
  local old_prefs = {}
  if args and args.old_st_store and args.old_st_store.preferences then
    old_prefs = args.old_st_store.preferences
  end

  local generation = (device:get_field(F_INFO_CHANGED_GENERATION) or 0) + 1
  device:set_field(F_INFO_CHANGED_GENERATION, generation, { persist = false })

  safe_delay(device, INFO_CHANGED_DEBOUNCE_SECONDS, "debounced preference apply", function()
    if device:get_field(F_INFO_CHANGED_GENERATION) ~= generation then
      return
    end
    apply_preferences_now(driver, device, old_prefs)
  end)
end

local namron_panel_heater_driver = {
  supported_capabilities = {
    Switch,
    TemperatureMeasurement,
    ThermostatHeatingSetpoint,
    ThermostatMode,
    ThermostatOperatingState,
    PowerMeter,
    EnergyMeter,
    VoltageMeasurement,
    CurrentMeasurement,
    ContactSensor,
    capabilities.refresh,
    capabilities.configuration,
  },
  zigbee_handlers = {
    attr = {
      [THERMOSTAT_CLUSTER_ID] = {
        [ATTR_LOCAL_TEMPERATURE] = guarded("localTemperature attr", thermostat_temperature_handler),
        [ATTR_LOCAL_TEMPERATURE_CALIBRATION] = guarded("temperature calibration attr", local_temperature_calibration_handler),
        [ATTR_OCCUPIED_HEATING_SETPOINT] = guarded("heatingSetpoint attr", heating_setpoint_handler),
        [ATTR_SYSTEM_MODE] = guarded("systemMode attr", system_mode_handler),
        [ATTR_THERMOSTAT_RUNNING_STATE] = guarded("runningState attr", running_state_handler),
        [ATTR_DISPLAY_BRIGHTNESS] = guarded("display brightness attr", display_brightness_handler),
        [ATTR_DISPLAY_AUTO_OFF] = guarded("display auto-off attr", display_auto_off_handler),
        [ATTR_POWER_UP_STATUS] = guarded("power-up status attr", power_up_status_handler),
        [ATTR_WINDOW_DETECTION] = guarded("window detection attr", window_detection_handler),
        [ATTR_HYSTERESIS] = guarded("hysteresis attr", hysteresis_handler),
        [ATTR_WINDOW_OPEN] = guarded("window open attr", window_open_handler),
      },
      [THERMOSTAT_UI_CLUSTER_ID] = {
        [ATTR_KEYPAD_LOCKOUT] = guarded("keypadLockout attr", keypad_lockout_handler),
      },
      [SIMPLE_METERING_CLUSTER_ID] = {
        [ATTR_CURRENT_SUMMATION_DELIVERED] = guarded("energy attr", simple_metering_handler),
        [ATTR_METERING_MULTIPLIER] = guarded("energy multiplier attr", metering_multiplier_handler),
        [ATTR_METERING_DIVISOR] = guarded("energy divisor attr", metering_divisor_handler),
      },
      [ELECTRICAL_MEASUREMENT_CLUSTER_ID] = {
        [ATTR_RMS_VOLTAGE] = guarded("voltage attr", rms_voltage_handler),
        [ATTR_RMS_CURRENT] = guarded("current attr", rms_current_handler),
        [ATTR_ACTIVE_POWER] = guarded("power attr", active_power_handler),
        [ATTR_AC_VOLTAGE_MULTIPLIER] = guarded("voltage multiplier attr", set_multiplier_field(F_VOLTAGE_MULTIPLIER)),
        [ATTR_AC_VOLTAGE_DIVISOR] = guarded("voltage divisor attr", set_multiplier_field(F_VOLTAGE_DIVISOR)),
        [ATTR_AC_CURRENT_MULTIPLIER] = guarded("current multiplier attr", set_multiplier_field(F_CURRENT_MULTIPLIER)),
        [ATTR_AC_CURRENT_DIVISOR] = guarded("current divisor attr", set_multiplier_field(F_CURRENT_DIVISOR)),
        [ATTR_AC_POWER_MULTIPLIER] = guarded("power multiplier attr", set_multiplier_field(F_POWER_MULTIPLIER)),
        [ATTR_AC_POWER_DIVISOR] = guarded("power divisor attr", set_multiplier_field(F_POWER_DIVISOR)),
      },
    },
  },
  capability_handlers = {
    [Switch.ID] = {
      [Switch.commands.on.NAME] = guarded("switch on", switch_on),
      [Switch.commands.off.NAME] = guarded("switch off", switch_off),
    },
    [ThermostatHeatingSetpoint.ID] = {
      [ThermostatHeatingSetpoint.commands.setHeatingSetpoint.NAME] = guarded("set heating setpoint", set_heating_setpoint),
    },
    [ThermostatMode.ID] = {
      [ThermostatMode.commands.setThermostatMode.NAME] = guarded("set thermostat mode", set_thermostat_mode),
      [ThermostatMode.commands.off.NAME] = guarded("thermostat off", thermostat_mode_setter(ThermostatMode.thermostatMode.off.NAME)),
      [ThermostatMode.commands.heat.NAME] = guarded("thermostat heat", thermostat_mode_setter(ThermostatMode.thermostatMode.heat.NAME)),
    },
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = guarded("refresh", refresh),
    },
    [capabilities.configuration.ID] = {
      [capabilities.configuration.commands.configure.NAME] = guarded("configuration command", configure_device),
    },
  },
  lifecycle_handlers = {
    added = guarded("added", device_added),
    init = guarded("init", device_init),
    doConfigure = guarded("doConfigure", configure_device),
    driverSwitched = guarded("driverSwitched", configure_device),
    infoChanged = guarded("infoChanged", apply_preferences),
  },
  health_check = false,
  shared_device_thread_enabled = true,
  current_config_version = 1,
}

local driver = ZigbeeDriver(DRIVER_NAME, namron_panel_heater_driver)
driver:run()
