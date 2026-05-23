-- TS0219 Zigbee siren Edge driver
-- SmartThings Edge driver for exact, known TS0219 siren fingerprints.
--
-- Primary control path:
--   IAS Warning Device cluster 0x0502 StartWarning command.
-- Feedback path:
--   IAS Zone cluster 0x0500 ZoneStatus / ZoneStatusChangeNotification.
-- Device-specific settings:
--   IAS WD attributes observed on TS0219/R7051 units:
--     0x0000 MaxDuration / duration (Uint16)
--     0x0001 LED brightness / strobe intensity (Uint8, experimental)
--     0x0002 Siren volume (Uint8, 0-100)
--     0x0003 Observed on interviews, retained as diagnostic field only.

local capabilities = require "st.capabilities"
local log = require "log"
local ZigbeeDriver = require "st.zigbee"
local clusters = require "st.zigbee.zcl.clusters"
local constants = require "st.zigbee.constants"
local data_types = require "st.zigbee.data_types"
local cluster_base = require "st.zigbee.cluster_base"
local device_management = require "st.zigbee.device_management"

local IASZone = clusters.IASZone
local IASWD = clusters.IASWD
local Basic = clusters.Basic
local PowerConfiguration = clusters.PowerConfiguration

local ENDPOINT = 0x01

local CAP = {
  siren_volume = "oceancircle09600.sirenVolume",
  alarm_duration = "oceancircle09600.alarmDuration",
  siren_level = "oceancircle09600.sirenLevel",
  strobe = "oceancircle09600.strobe",
  strobe_level = "oceancircle09600.strobeLevel",
  strobe_duty_cycle = "oceancircle09600.strobeDutyCycle",
  led_brightness = "oceancircle09600.ledBrightness",
  battery_voltage = "oceancircle09600.batteryVoltage",
  ac_connected = "oceancircle09600.acConnected",
}

local IASWD_ATTR_MAX_DURATION = 0x0000
local IASWD_ATTR_LED_BRIGHTNESS = 0x0001
local IASWD_ATTR_VOLUME = 0x0002
local IASWD_ATTR_UNKNOWN_3 = 0x0003

local BASIC_POWER_SOURCE_UNKNOWN = 0x00
local BASIC_POWER_SOURCE_SINGLE_PHASE_MAINS = 0x01
local BASIC_POWER_SOURCE_THREE_PHASE_MAINS = 0x02
local BASIC_POWER_SOURCE_BATTERY = 0x03
local BASIC_POWER_SOURCE_DC_SOURCE = 0x04
local BASIC_POWER_SOURCE_EMERGENCY_MAINS_CONSTANTLY_POWERED = 0x05
local BASIC_POWER_SOURCE_EMERGENCY_MAINS_AND_TRANSFER_SWITCH = 0x06
local BASIC_POWER_SOURCE_BACKUP_MASK = 0x80

local IASWD_LEVEL = {
  low = IASWD.types.IaswdLevel.LOW_LEVEL,
  medium = IASWD.types.IaswdLevel.MEDIUM_LEVEL,
  high = IASWD.types.IaswdLevel.HIGH_LEVEL,
  very_high = IASWD.types.IaswdLevel.VERY_HIGH_LEVEL,
}

local function clamp(value, min, max)
  value = tonumber(value) or min
  if value < min then return min end
  if value > max then return max end
  return math.floor(value + 0.5)
end

local function pref(device, key, fallback)
  local value = device.preferences and device.preferences[key]
  if value == nil then return fallback end
  return value
end

local function get_field_or_pref(device, field, pref_name, fallback)
  local value = device:get_field(field)
  if value ~= nil then return value end
  return pref(device, pref_name, fallback)
end

local function cap_obj(cap_id)
  return capabilities[cap_id]
end

local function log_info(fmt, ...)
  log.info(string.format(fmt, ...))
end

local function log_debug(fmt, ...)
  log.debug(string.format(fmt, ...))
end

local function emit_custom(device, cap_id, attr_name, value)
  local cap = cap_obj(cap_id)
  if cap ~= nil and cap[attr_name] ~= nil then
    device:emit_event(cap[attr_name](value))
  end
end

local function emit_alarm_duration(device, duration)
  emit_custom(device, CAP.alarm_duration, "alarmDuration", clamp(duration, 0, 3600))
end


local function emit_siren_level(device, level_name)
  emit_custom(device, CAP.siren_level, "sirenLevel", level_name or "high")
end

local function emit_strobe(device, enabled)
  emit_custom(device, CAP.strobe, "strobe", enabled and "on" or "off")
end

local function emit_strobe_level(device, level_name)
  emit_custom(device, CAP.strobe_level, "strobeLevel", level_name or "high")
end

local function emit_strobe_duty_cycle(device, duty_cycle)
  emit_custom(device, CAP.strobe_duty_cycle, "strobeDutyCycle", clamp(duty_cycle, 0, 10))
end

local function emit_led_brightness(device, level)
  emit_custom(device, CAP.led_brightness, "ledBrightness", clamp(level, 0, 100))
end

local function emit_siren_volume(device, volume)
  local normalized = clamp(volume, 0, 100)
  device:emit_event(capabilities.audioVolume.volume(normalized))
  emit_custom(device, CAP.siren_volume, "sirenVolume", normalized)
end

local function emit_battery_voltage(device, millivolts)
  emit_custom(device, CAP.battery_voltage, "batteryVoltage", clamp(millivolts, 0, 10000))
end

local function emit_ac_connected(device, connected)
  emit_custom(device, CAP.ac_connected, "acConnected", connected and "connected" or "disconnected")
end

local function remember_setting(device, field, value, persist)
  device:set_field(field, value, {persist = persist ~= false})
end

local function emit_alarm_state(device, active, alarm_value, force)
  -- IAS Zone can arrive twice for the same transition: once as a
  -- ZoneStatusChangeNotification and once as a ZoneStatus attribute report.
  --
  -- Important UI detail:
  -- Command-side optimistic events must NOT update the IAS dedupe field.
  -- The SmartThings app behaves better when the later real IAS Zone confirmation
  -- is still emitted. Therefore only non-forced IAS-originated updates are
  -- deduplicated.
  if not force then
    local last = device:get_field("lastIasAlarmActive")
    if last ~= nil and last == active then
      log_debug("suppress duplicate IAS Zone active=%s", tostring(active))
      return
    end
    remember_setting(device, "lastIasAlarmActive", active == true, false)
  end

  if active then
    if alarm_value == "siren" then
      device:emit_event(capabilities.alarm.alarm.siren())
    elseif alarm_value == "strobe" then
      device:emit_event(capabilities.alarm.alarm.strobe())
    else
      device:emit_event(capabilities.alarm.alarm.both())
    end
    device:emit_event(capabilities.switch.switch.on())
  else
    device:emit_event(capabilities.alarm.alarm.off())
    device:emit_event(capabilities.switch.switch.off())
  end
end

local function get_duration(device)
  return clamp(get_field_or_pref(device, "alarmDuration", "defaultDuration", 180), 0, 3600)
end

local function get_siren_level_name(device)
  local level_name = get_field_or_pref(device, "sirenLevel", "defaultSirenLevel", "high")
  return IASWD_LEVEL[level_name] ~= nil and level_name or "high"
end

local function get_strobe_level_name(device)
  local level_name = get_field_or_pref(device, "strobeLevel", "defaultStrobeLevel", "high")
  return IASWD_LEVEL[level_name] ~= nil and level_name or "high"
end

local function get_strobe_enabled(device)
  local stored = device:get_field("strobe")
  if stored ~= nil then return stored == true end
  return pref(device, "defaultStrobe", true) == true
end

local function get_strobe_duty_cycle(device)
  return clamp(get_field_or_pref(device, "strobeDutyCycle", "strobeDutyCycle", 0), 0, 10)
end

local function get_led_brightness(device)
  return clamp(get_field_or_pref(device, "ledBrightness", "ledBrightness", 50), 0, 100)
end

local function build_siren_configuration(mode, level, strobe)
  local cfg = IASWD.types.SirenConfiguration(0)
  cfg:set_warning_mode(mode)
  cfg:set_siren_level(level)
  cfg:set_strobe(strobe and IASWD.types.Strobe.USE_STROBE or IASWD.types.Strobe.NO_STROBE)
  return cfg
end

local function disable_default_response(message)
  if message and message.body and message.body.zcl_header and message.body.zcl_header.frame_ctrl then
    message.body.zcl_header.frame_ctrl:set_disable_default_response()
  end
  return message
end

local function write_iaswd_attribute(device, attr_id, data_type, value)
  log_debug("write IASWD attr 0x%04X = %s", attr_id, tostring(value))
  local data = data_types.validate_or_build_type(value, data_type)
  local message = cluster_base.write_attribute(device, data_types.ClusterId(IASWD.ID), attr_id, data)
  device:send(disable_default_response(message):to_endpoint(ENDPOINT))
end

local function read_iaswd_attribute(device, attr_id)
  log_debug("read IASWD attr 0x%04X", attr_id)
  device:send(cluster_base.read_attribute(device, data_types.ClusterId(IASWD.ID), attr_id):to_endpoint(ENDPOINT))
end

local function write_max_duration(device, duration)
  write_iaswd_attribute(device, IASWD_ATTR_MAX_DURATION, data_types.Uint16, clamp(duration, 0, 3600))
end

local function write_volume(device, volume)
  write_iaswd_attribute(device, IASWD_ATTR_VOLUME, data_types.Uint8, clamp(volume, 0, 100))
end

local function write_led_brightness(device, brightness)
  write_iaswd_attribute(device, IASWD_ATTR_LED_BRIGHTNESS, data_types.Uint8, clamp(brightness, 0, 100))
end

local function send_start_warning(device, mode, level, duration, strobe, strobe_duty_cycle, strobe_level)
  log_info("send StartWarning mode=%s level=%s duration=%s strobe=%s duty=%s strobeLevel=%s", tostring(mode), tostring(level), tostring(duration), tostring(strobe), tostring(strobe_duty_cycle), tostring(strobe_level))
  local cfg = build_siren_configuration(mode, level, strobe)
  local command = IASWD.commands.StartWarning(
    device,
    cfg,
    data_types.Uint16(duration),
    data_types.Uint8(strobe_duty_cycle),
    IASWD.types.IaswdLevel(strobe_level)
  )
  device:send(disable_default_response(command):to_endpoint(ENDPOINT))
end

local function read_device_state(device)
  log_info("refresh/read device state")
  device:send(PowerConfiguration.attributes.BatteryPercentageRemaining:read(device):to_endpoint(ENDPOINT))
  device:send(PowerConfiguration.attributes.BatteryVoltage:read(device):to_endpoint(ENDPOINT))
  device:send(Basic.attributes.PowerSource:read(device):to_endpoint(ENDPOINT))
  device:send(IASZone.attributes.ZoneStatus:read(device):to_endpoint(ENDPOINT))
  device:send(IASWD.attributes.MaxDuration:read(device):to_endpoint(ENDPOINT))
  read_iaswd_attribute(device, IASWD_ATTR_VOLUME)
  read_iaswd_attribute(device, IASWD_ATTR_LED_BRIGHTNESS)
  read_iaswd_attribute(device, IASWD_ATTR_UNKNOWN_3)
end

local function emit_all_settings(device)
  emit_alarm_duration(device, get_duration(device))
  emit_siren_level(device, get_siren_level_name(device))
  emit_strobe(device, get_strobe_enabled(device))
  emit_strobe_level(device, get_strobe_level_name(device))
  emit_strobe_duty_cycle(device, get_strobe_duty_cycle(device))
  emit_led_brightness(device, get_led_brightness(device))
end

local function initialize_settings(device)
  local duration = clamp(pref(device, "defaultDuration", 180), 0, 3600)
  local volume = clamp(pref(device, "defaultVolume", 50), 0, 100)
  remember_setting(device, "alarmDuration", duration)
  remember_setting(device, "sirenVolume", volume)
  remember_setting(device, "sirenLevel", pref(device, "defaultSirenLevel", "high"))
  remember_setting(device, "strobe", pref(device, "defaultStrobe", true) == true)
  remember_setting(device, "strobeLevel", pref(device, "defaultStrobeLevel", "high"))
  remember_setting(device, "strobeDutyCycle", clamp(pref(device, "strobeDutyCycle", 0), 0, 10))
  remember_setting(device, "ledBrightness", clamp(pref(device, "ledBrightness", 50), 0, 100))
  return duration, volume
end

local function ensure_settings(device)
  -- Used during init after driver restart/update. Do not overwrite persisted
  -- runtime settings that may have been changed from the app.
  if device:get_field("alarmDuration") == nil then
    remember_setting(device, "alarmDuration", clamp(pref(device, "defaultDuration", 180), 0, 3600))
  end
  if device:get_field("sirenVolume") == nil then
    remember_setting(device, "sirenVolume", clamp(pref(device, "defaultVolume", 50), 0, 100))
  end
  if device:get_field("sirenLevel") == nil then
    remember_setting(device, "sirenLevel", pref(device, "defaultSirenLevel", "high"))
  end
  if device:get_field("strobe") == nil then
    remember_setting(device, "strobe", pref(device, "defaultStrobe", true) == true)
  end
  if device:get_field("strobeLevel") == nil then
    remember_setting(device, "strobeLevel", pref(device, "defaultStrobeLevel", "high"))
  end
  if device:get_field("strobeDutyCycle") == nil then
    remember_setting(device, "strobeDutyCycle", clamp(pref(device, "strobeDutyCycle", 0), 0, 10))
  end
  if device:get_field("ledBrightness") == nil then
    remember_setting(device, "ledBrightness", clamp(pref(device, "ledBrightness", 50), 0, 100))
  end
end

local function start_alarm(driver, device, command, forced_strobe, requested_alarm_value, strobe_only)
  log_info("start alarm requested")
  local duration = get_duration(device)
  if duration <= 0 then duration = 1 end

  -- The R7051/TS0219 does not expose meaningfully distinct user-facing tones in
  -- SmartThings testing, so keep warning mode internal and fixed for audible
  -- alarms. Duration, siren level, strobe, strobe level, and duty cycle remain
  -- configurable.
  local level_name = get_siren_level_name(device)
  local strobe_level_name = get_strobe_level_name(device)
  local strobe = forced_strobe
  if strobe == nil then strobe = get_strobe_enabled(device) end
  local duty = get_strobe_duty_cycle(device)

  local mode = IASWD.types.WarningMode.BURGLAR
  local level = IASWD_LEVEL[level_name] or IASWD.types.IaswdLevel.HIGH_LEVEL
  local strobe_level = IASWD_LEVEL[strobe_level_name] or IASWD.types.IaswdLevel.HIGH_LEVEL

  if strobe_only == true then
    -- Best-effort semantic mapping for the standard alarm.strobe command.
    -- Some TS0219/R7051 firmware may still require an audible warning mode for
    -- visible strobe behavior, but this avoids making "strobe" identical to "both".
    mode = IASWD.types.WarningMode.STOP
    level = IASWD.types.IaswdLevel.LOW_LEVEL
    strobe = true
    requested_alarm_value = "strobe"
  elseif requested_alarm_value == nil then
    requested_alarm_value = strobe and "both" or "siren"
  end

  log_info(
    "start warning mode=%s level=%s duration=%s strobe=%s duty=%s strobeLevel=%s requested=%s",
    strobe_only and "stop/strobe-only" or "burglar",
    tostring(level_name),
    tostring(duration),
    tostring(strobe),
    tostring(duty),
    tostring(strobe_level_name),
    tostring(requested_alarm_value)
  )

  send_start_warning(device, mode, level, duration, strobe, duty, strobe_level)
  emit_alarm_state(device, true, requested_alarm_value, true)
end

local function stop_alarm(driver, device, command)
  log_info("stop alarm requested")
  send_start_warning(
    device,
    IASWD.types.WarningMode.STOP,
    IASWD.types.IaswdLevel.LOW_LEVEL,
    0,
    false,
    0,
    IASWD.types.IaswdLevel.LOW_LEVEL
  )
  emit_alarm_state(device, false, "off", true)
end

local function set_volume(driver, device, command)
  local volume = command.args and (command.args.volume or command.args.sirenVolume or command.args[1])
  volume = clamp(volume, 0, 100)
  log_info("set volume=%s", tostring(volume))
  remember_setting(device, "sirenVolume", volume)
  write_volume(device, volume)
  emit_siren_volume(device, volume)
end

local function set_alarm_duration(driver, device, command)
  local duration = command.args and (command.args.duration or command.args.alarmDuration or command.args[1])
  duration = clamp(duration, 0, 3600)
  log_info("set duration=%s", tostring(duration))
  remember_setting(device, "alarmDuration", duration)
  write_max_duration(device, duration)
  emit_alarm_duration(device, duration)
end

local function set_siren_level(driver, device, command)
  local level_name = command.args and (command.args.level or command.args.sirenLevel or command.args[1]) or "high"
  if IASWD_LEVEL[level_name] == nil then level_name = "high" end
  log_info("set siren level=%s", tostring(level_name))
  remember_setting(device, "sirenLevel", level_name)
  emit_siren_level(device, level_name)
end

local function set_strobe(driver, device, command)
  local strobe_value = command.args and (command.args.strobe or command.args[1])
  local enabled = strobe_value == true or strobe_value == "on" or strobe_value == "true" or strobe_value == 1
  log_info("set strobe=%s", tostring(enabled))
  remember_setting(device, "strobe", enabled)
  emit_strobe(device, enabled)
end

local function set_strobe_level(driver, device, command)
  local level_name = command.args and (command.args.level or command.args.strobeLevel or command.args[1]) or "high"
  if IASWD_LEVEL[level_name] == nil then level_name = "high" end
  log_info("set strobe level=%s", tostring(level_name))
  remember_setting(device, "strobeLevel", level_name)
  emit_strobe_level(device, level_name)
end

local function set_strobe_duty_cycle(driver, device, command)
  local duty_cycle = command.args and (command.args.dutyCycle or command.args.strobeDutyCycle or command.args[1])
  duty_cycle = clamp(duty_cycle, 0, 10)
  log_info("set strobe duty cycle=%s", tostring(duty_cycle))
  remember_setting(device, "strobeDutyCycle", duty_cycle)
  emit_strobe_duty_cycle(device, duty_cycle)
end

local function set_led_brightness(driver, device, command)
  local brightness = command.args and (command.args.brightness or command.args.ledBrightness or command.args[1])
  brightness = clamp(brightness, 0, 100)
  log_info("set LED brightness=%s", tostring(brightness))
  remember_setting(device, "ledBrightness", brightness)
  write_led_brightness(device, brightness)
  emit_led_brightness(device, brightness)
end

local function refresh(driver, device, command)
  read_device_state(device)
  emit_all_settings(device)
end

local function zone_status_value(zone_status)
  if type(zone_status) == "table" then
    if zone_status.value ~= nil then return zone_status.value end
    if zone_status.value_cache ~= nil then return zone_status.value_cache end
  end
  return tonumber(zone_status) or 0
end

local function is_alarm1_set(zone_status)
  if type(zone_status) == "table" and zone_status.is_alarm1_set ~= nil then
    return zone_status:is_alarm1_set()
  end
  return (zone_status_value(zone_status) % 2) == 1
end

local function emit_alarm_from_zone_status(driver, device, zone_status, zb_rx)
  local raw = zone_status_value(zone_status)
  local active = is_alarm1_set(zone_status)
  log_info("IAS Zone status=0x%04X active=%s", raw, tostring(active))
  emit_alarm_state(device, active, "both", false)
end

local function zone_status_attr_handler(driver, device, zone_status, zb_rx)
  emit_alarm_from_zone_status(driver, device, zone_status, zb_rx)
end

local function zone_status_change_handler(driver, device, zb_rx)
  local zone_status = zb_rx.body.zcl_body.zone_status
  emit_alarm_from_zone_status(driver, device, zone_status, zb_rx)
end

local function battery_percentage_handler(driver, device, value, zb_rx)
  -- ZCL BatteryPercentageRemaining is reported in half-percent increments.
  local pct = clamp((value.value or 0) / 2, 0, 100)
  log_info("battery percentage raw=%s pct=%s", tostring(value.value), tostring(pct))
  device:emit_event(capabilities.battery.battery(pct))
end

local function battery_voltage_handler(driver, device, value, zb_rx)
  -- ZCL BatteryVoltage is reported in 100 mV units.
  local millivolts = clamp((value.value or 0) * 100, 0, 10000)
  log_info("battery voltage raw=%s mv=%s", tostring(value.value), tostring(millivolts))
  remember_setting(device, "batteryVoltageMv", millivolts)
  emit_battery_voltage(device, millivolts)
end

local function power_source_handler(driver, device, value, zb_rx)
  local raw = tonumber(value.value) or BASIC_POWER_SOURCE_UNKNOWN
  local base = raw
  if raw >= BASIC_POWER_SOURCE_BACKUP_MASK then
    base = raw - BASIC_POWER_SOURCE_BACKUP_MASK
  end

  local source = capabilities.powerSource.powerSource.unknown
  local ac_connected = nil

  if base == BASIC_POWER_SOURCE_BATTERY
      or base == BASIC_POWER_SOURCE_EMERGENCY_MAINS_AND_TRANSFER_SWITCH then
    -- R7051-specific behavior observed in testing:
    --   0x02 = externally powered / USB connected
    --   0x06 = emergency/transfer value when running from backup battery
    source = capabilities.powerSource.powerSource.battery
    ac_connected = false
  elseif base == BASIC_POWER_SOURCE_DC_SOURCE then
    source = capabilities.powerSource.powerSource.dc
    ac_connected = true
  elseif base == BASIC_POWER_SOURCE_SINGLE_PHASE_MAINS
      or base == BASIC_POWER_SOURCE_THREE_PHASE_MAINS
      or base == BASIC_POWER_SOURCE_EMERGENCY_MAINS_CONSTANTLY_POWERED then
    source = capabilities.powerSource.powerSource.mains
    ac_connected = true
  end

  log_info("power source raw=0x%02X base=0x%02X source=%s ac=%s", raw, base, tostring(source), tostring(ac_connected))
  device:emit_event(source())
  if ac_connected ~= nil then
    emit_ac_connected(device, ac_connected)
  end
end

local function max_duration_handler(driver, device, value, zb_rx)
  -- Attribute 0x0000 is the IAS WD MaxDuration attribute. On the R7051 it can
  -- report a very high/sentinel value such as 0xFFFE. Do not treat it as the
  -- user's selected alarm duration; keep the UI duration as our runtime setting.
  local raw = tonumber(value.value) or 0
  local max_duration = clamp(raw, 0, 3600)
  log_info("IASWD maxDuration raw=%s clamped=%s", tostring(raw), tostring(max_duration))
  remember_setting(device, "iaswdMaxDuration", raw)
  emit_alarm_duration(device, get_duration(device))
end

local function iaswd_volume_handler(driver, device, value, zb_rx)
  local volume = clamp(value.value, 0, 100)
  log_info("IASWD volume=%s", tostring(volume))
  remember_setting(device, "sirenVolume", volume)
  emit_siren_volume(device, volume)
end

local function iaswd_led_brightness_handler(driver, device, value, zb_rx)
  local brightness = clamp(value.value, 0, 100)
  log_info("IASWD LED brightness=%s", tostring(brightness))
  remember_setting(device, "ledBrightness", brightness)
  emit_led_brightness(device, brightness)
end

local function do_init(driver, device)
  log_info("lifecycle init")
  ensure_settings(device)
  emit_siren_volume(device, get_field_or_pref(device, "sirenVolume", "defaultVolume", 50))
  emit_all_settings(device)
  read_device_state(device)
end

local function do_added(driver, device)
  log_info("lifecycle added")
  local _, volume = initialize_settings(device)

  emit_alarm_state(device, false, "off", true)
  device:emit_event(capabilities.powerSource.powerSource.unknown())
  emit_siren_volume(device, volume)
  emit_all_settings(device)
  -- Do not emit acConnected here. Wait for the real Basic.PowerSource value so
  -- the app does not briefly show a false "disconnected" state for a plugged-in siren.
end

local function do_configure(driver, device)
  log_info("lifecycle configure")
  local hub_eui = driver.environment_info and driver.environment_info.hub_zigbee_eui

  if hub_eui ~= nil then
    device:send(device_management.build_bind_request(device, PowerConfiguration.ID, hub_eui, ENDPOINT))
  else
    log.warn("hub Zigbee EUI not available yet; skipping PowerConfiguration bind")
  end

  device:send(PowerConfiguration.attributes.BatteryPercentageRemaining:configure_reporting(device, 30, 21600, 1):to_endpoint(ENDPOINT))
  device:send(PowerConfiguration.attributes.BatteryVoltage:configure_reporting(device, 30, 21600, 1):to_endpoint(ENDPOINT))

  if pref(device, "bindIASZone", true) and hub_eui ~= nil then
    device:send(device_management.build_bind_request(device, IASZone.ID, hub_eui, ENDPOINT))
  elseif pref(device, "bindIASZone", true) then
    log.warn("hub Zigbee EUI not available yet; skipping IAS Zone bind")
  end

  if pref(device, "writeWooxAttrs", true) then
    write_max_duration(device, get_duration(device))
    write_volume(device, get_field_or_pref(device, "sirenVolume", "defaultVolume", 50))
    write_led_brightness(device, get_led_brightness(device))
  end

  emit_all_settings(device)
  read_device_state(device)
  device:configure()
end

local function driver_switched(driver, device)
  log_info("lifecycle driverSwitched")
  initialize_settings(device)
  emit_siren_volume(device, get_field_or_pref(device, "sirenVolume", "defaultVolume", 50))
  emit_all_settings(device)
  do_configure(driver, device)
end

local function info_changed(driver, device, event, args)
  log_info("lifecycle infoChanged")
  if args and args.old_st_store and args.old_st_store.preferences and device.preferences then
    local old = args.old_st_store.preferences
    if old.defaultDuration ~= device.preferences.defaultDuration then
      remember_setting(device, "alarmDuration", clamp(device.preferences.defaultDuration, 0, 3600))
      emit_alarm_duration(device, device.preferences.defaultDuration)
      if pref(device, "writeWooxAttrs", true) then
        write_max_duration(device, device.preferences.defaultDuration)
      end
    end
    if old.defaultVolume ~= device.preferences.defaultVolume then
      remember_setting(device, "sirenVolume", clamp(device.preferences.defaultVolume, 0, 100))
      emit_siren_volume(device, device.preferences.defaultVolume)
      if pref(device, "writeWooxAttrs", true) then
        write_volume(device, device.preferences.defaultVolume)
      end
    end
    if old.defaultSirenLevel ~= device.preferences.defaultSirenLevel then
      remember_setting(device, "sirenLevel", device.preferences.defaultSirenLevel)
      emit_siren_level(device, get_siren_level_name(device))
    end
    if old.defaultStrobe ~= device.preferences.defaultStrobe then
      remember_setting(device, "strobe", device.preferences.defaultStrobe == true)
      emit_strobe(device, get_strobe_enabled(device))
    end
    if old.defaultStrobeLevel ~= device.preferences.defaultStrobeLevel then
      remember_setting(device, "strobeLevel", device.preferences.defaultStrobeLevel)
      emit_strobe_level(device, get_strobe_level_name(device))
    end
    if old.strobeDutyCycle ~= device.preferences.strobeDutyCycle then
      remember_setting(device, "strobeDutyCycle", clamp(device.preferences.strobeDutyCycle, 0, 10))
      emit_strobe_duty_cycle(device, get_strobe_duty_cycle(device))
    end
    if old.ledBrightness ~= device.preferences.ledBrightness then
      remember_setting(device, "ledBrightness", clamp(device.preferences.ledBrightness, 0, 100))
      emit_led_brightness(device, get_led_brightness(device))
      if pref(device, "writeWooxAttrs", true) then
        write_led_brightness(device, device.preferences.ledBrightness)
      end
    end
  end
end

local SUPPORTED_FINGERPRINTS = {
  ["_TYZB01_ynsiasng"] = "Woox R7051",
  ["_TYZB01_b6eaxdlh"] = "Immax NEO 07504L",
}

local function can_handle(opts, driver, device)
  local manufacturer = device:get_manufacturer()
  local model = device:get_model()
  local supported = model == "TS0219" and SUPPORTED_FINGERPRINTS[manufacturer] ~= nil
  if supported then
    log_info("matched TS0219 siren variant manufacturer=%s label=%s", tostring(manufacturer), tostring(SUPPORTED_FINGERPRINTS[manufacturer]))
  end
  return supported
end

local supported_capabilities = {
  capabilities.alarm,
  capabilities.switch,
  capabilities.battery,
  capabilities.powerSource,
  capabilities.audioVolume,
  capabilities.refresh,
}

for _, cap_id in pairs(CAP) do
  if capabilities[cap_id] ~= nil then
    table.insert(supported_capabilities, capabilities[cap_id])
  end
end

local driver_template = {
  supported_capabilities = supported_capabilities,
  capability_handlers = {
    [capabilities.switch.ID] = {
      [capabilities.switch.commands.on.NAME] = start_alarm,
      [capabilities.switch.commands.off.NAME] = stop_alarm,
    },
    [capabilities.alarm.ID] = {
      [capabilities.alarm.commands.both.NAME] = function(driver, device, command)
        start_alarm(driver, device, command, true, "both", false)
      end,
      [capabilities.alarm.commands.siren.NAME] = function(driver, device, command)
        start_alarm(driver, device, command, false, "siren", false)
      end,
      [capabilities.alarm.commands.strobe.NAME] = function(driver, device, command)
        start_alarm(driver, device, command, true, "strobe", true)
      end,
      [capabilities.alarm.commands.off.NAME] = stop_alarm,
    },
    [capabilities.audioVolume.ID] = {
      [capabilities.audioVolume.commands.setVolume.NAME] = set_volume,
    },
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = refresh,
    },
    [CAP.siren_volume] = {
      setSirenVolume = set_volume,
    },
    [CAP.alarm_duration] = {
      setAlarmDuration = set_alarm_duration,
    },
    [CAP.siren_level] = {
      setSirenLevel = set_siren_level,
    },
    [CAP.strobe] = {
      setStrobe = set_strobe,
    },
    [CAP.strobe_level] = {
      setStrobeLevel = set_strobe_level,
    },
    [CAP.strobe_duty_cycle] = {
      setStrobeDutyCycle = set_strobe_duty_cycle,
    },
    [CAP.led_brightness] = {
      setLedBrightness = set_led_brightness,
    },
  },
  zigbee_handlers = {
    cluster = {
      [IASZone.ID] = {
        [IASZone.client.commands.ZoneStatusChangeNotification.ID] = zone_status_change_handler,
      },
    },
    attr = {
      [IASZone.ID] = {
        [IASZone.attributes.ZoneStatus.ID] = zone_status_attr_handler,
      },
      [PowerConfiguration.ID] = {
        [PowerConfiguration.attributes.BatteryPercentageRemaining.ID] = battery_percentage_handler,
        [PowerConfiguration.attributes.BatteryVoltage.ID] = battery_voltage_handler,
      },
      [Basic.ID] = {
        [Basic.attributes.PowerSource.ID] = power_source_handler,
      },
      [IASWD.ID] = {
        [IASWD_ATTR_MAX_DURATION] = max_duration_handler,
        [IASWD_ATTR_VOLUME] = iaswd_volume_handler,
        [IASWD_ATTR_LED_BRIGHTNESS] = iaswd_led_brightness_handler,
        [IASWD_ATTR_UNKNOWN_3] = function(driver, device, value, zb_rx)
          remember_setting(device, "iaswdAttr0003", value.value)
        end,
      },
    },
  },
  lifecycle_handlers = {
    init = do_init,
    added = do_added,
    driverSwitched = driver_switched,
    doConfigure = do_configure,
    infoChanged = info_changed,
  },
  health_check = false,
  ias_zone_configuration_method = constants.IAS_ZONE_CONFIGURE_TYPE.AUTO_ENROLL_RESPONSE,
  can_handle = can_handle,
}

local woox_r7051 = ZigbeeDriver("TS0219 Siren", driver_template)
woox_r7051:run()
