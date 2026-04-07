-- Aqara FP300 Zigbee Edge Driver for SmartThings
-- Revised build: separates main presence from PIR motion, applies embedded
-- preferences consistently on configure/infoChanged, fixes preference ID
-- lengths, and keeps profile/capability handling aligned.

local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"
local clusters = require "st.zigbee.zcl.clusters"
local cluster_base = require "st.zigbee.cluster_base"
local device_management = require "st.zigbee.device_management"
local data_types = require "st.zigbee.data_types"
local utils = require "st.utils"
local log = require "log"

local target_distance_cap = capabilities["oceancircle09600.aqaratargetdistance"]

local TemperatureMeasurement = clusters.TemperatureMeasurement
local RelativeHumidity = clusters.RelativeHumidity
local IlluminanceMeasurement = clusters.IlluminanceMeasurement

local AQARA_CLUSTER_ID = 0xFCC0
local AQARA_CLUSTER = { ID = AQARA_CLUSTER_ID, NAME = "AqaraManufacturerSpecific" }
local AQARA_MFG_CODE = 0x115F
local FP300_MODEL = "lumi.sensor_occupy.agl8"

local FIELDS = {
  DETECTION_RANGE_MASK = "fp300_detection_range_mask",
  DETECTION_RANGE_RAW = "fp300_detection_range_raw",
  DETECTION_RANGE_PREFIX = "fp300_detection_range_prefix",
  TARGET_DISTANCE_METERS = "fp300_target_distance_meters",
  LED_SCHEDULE_RAW = "fp300_led_schedule_raw",
  INFO_CHANGED_GENERATION = "fp300_infochanged_generation",
}

local INFO_CHANGED_DEBOUNCE_SECONDS = 1

local ATTR = {
  AQARA_ATTRIBUTE_REPORT = 0x00F7,
  RESTART_DEVICE = 0x00E8,
  PREVENT_LEAVE = 0x00FC,
  BATTERY_VOLTAGE = 0x0017,
  MOTION_SENSITIVITY = 0x010C,
  PRESENCE = 0x0142,
  PIR_DETECTION = 0x014D,
  PIR_DETECTION_INTERVAL = 0x014F,
  SPATIAL_LEARNING = 0x0157,
  AI_ADAPTIVE_SENSITIVITY = 0x015D,
  AI_INTERFERENCE_IDENT = 0x015E,
  TARGET_DISTANCE = 0x015F,
  TEMP_HUMIDITY_SAMPLING = 0x0170,
  TEMP_HUMIDITY_SAMPLING_PERIOD = 0x0162,
  TEMP_REPORTING_INTERVAL = 0x0163,
  TEMP_REPORTING_THRESHOLD = 0x0164,
  TEMP_REPORTING_MODE = 0x0165,
  HUMIDITY_REPORTING_INTERVAL = 0x016A,
  HUMIDITY_REPORTING_THRESHOLD = 0x016B,
  HUMIDITY_REPORTING_MODE = 0x016C,
  LIGHT_SAMPLING = 0x0192,
  LIGHT_SAMPLING_PERIOD = 0x0193,
  LIGHT_REPORTING_INTERVAL = 0x0194,
  LIGHT_REPORTING_THRESHOLD = 0x0195,
  LIGHT_REPORTING_MODE = 0x0196,
  ABSENCE_DELAY_TIMER = 0x0197,
  TRACK_TARGET_DISTANCE = 0x0198,
  PRESENCE_DETECTION_OPTIONS = 0x0199,
  DETECTION_RANGE_RAW = 0x019A,
  LED_DISABLED_NIGHT = 0x0203,
  LED_SCHEDULE_RAW = 0x023E,
}

local STANDARD_REFRESHES = {
  function(device) return TemperatureMeasurement.attributes.MeasuredValue:read(device) end,
  function(device) return RelativeHumidity.attributes.MeasuredValue:read(device) end,
  function(device) return IlluminanceMeasurement.attributes.MeasuredValue:read(device) end,
}

local CUSTOM_REFRESH_ATTRS = {
  ATTR.PREVENT_LEAVE,
  ATTR.BATTERY_VOLTAGE,
  ATTR.PRESENCE,
  ATTR.PIR_DETECTION,
  ATTR.TARGET_DISTANCE,
  ATTR.DETECTION_RANGE_RAW,
  ATTR.LED_SCHEDULE_RAW,
}

local function can_handle_fp300(_, _, device)
  local model = device:get_model()
  local manufacturer = device:get_manufacturer()
  if model ~= FP300_MODEL then
    return false
  end
  return manufacturer == "Aqara" or manufacturer == "LUMI"
end

local function safe_send(device, msg, label)
  if msg == nil then return false end
  local ok, err = pcall(function() device:send(msg) end)
  if not ok then
    log.warn(string.format("[FP300][%s] send failed for %s: %s", device.label or device.id or "?", label or "message", tostring(err)))
    return false
  end
  return true
end

local function safe_build_send(device, label, builder)
  local ok, msg_or_err = pcall(builder)
  if not ok then
    log.warn(string.format("[FP300][%s] message build failed for %s: %s", device.label or device.id or "?", label or "message", tostring(msg_or_err)))
    return false
  end
  return safe_send(device, msg_or_err, label)
end

local function raw_value(value)
  if type(value) == "table" and value.value ~= nil then
    return value.value
  end
  return value
end

local function get_field_value(device, field_name)
  local value = device:get_field(field_name)
  return value
end

local function get_field_number(device, field_name, default)
  local value = get_field_value(device, field_name)
  if value == nil then
    return default
  end

  local number_value = tonumber(value)
  if number_value == nil then
    return default
  end

  return number_value
end

local function format_value_for_log(value)
  local raw = raw_value(value)
  if type(raw) == "string" then
    local bytes = {}
    for i = 1, #raw do
      bytes[#bytes + 1] = string.format("%02X", raw:byte(i))
    end
    return string.format("0x%s", table.concat(bytes))
  end
  return tostring(raw)
end

local function verification_field_name(attribute_id)
  return string.format("fp300_verify_0x%04X", attribute_id)
end

local function verification_timeout_field_name(attribute_id)
  return string.format("fp300_verify_timeout_0x%04X", attribute_id)
end

local function verification_token_field_name(attribute_id)
  return string.format("fp300_verify_token_0x%04X", attribute_id)
end

local function last_requested_field_name(attribute_id)
  return string.format("fp300_last_requested_0x%04X", attribute_id)
end

local function pending_requested_field_name(attribute_id)
  return string.format("fp300_pending_requested_0x%04X", attribute_id)
end

local function clear_verification_pending(device, attribute_id)
  device:set_field(verification_field_name(attribute_id), nil, { persist = false })
  device:set_field(verification_timeout_field_name(attribute_id), nil, { persist = false })
  device:set_field(verification_token_field_name(attribute_id), nil, { persist = false })
  device:set_field(pending_requested_field_name(attribute_id), nil, { persist = false })
end

local function mark_verification_pending(device, attribute_id, label, expected_value)
  local stored_label = label or string.format("0x%04X", attribute_id)
  local next_token = (get_field_number(device, verification_token_field_name(attribute_id), 0) or 0) + 1

  device:set_field(verification_field_name(attribute_id), stored_label, { persist = false })
  device:set_field(verification_timeout_field_name(attribute_id), stored_label, { persist = false })
  device:set_field(verification_token_field_name(attribute_id), next_token, { persist = false })
  device:set_field(pending_requested_field_name(attribute_id), expected_value, { persist = false })

  return next_token, stored_label
end

local function consume_verification_pending(device, attribute_id)
  local label = device:get_field(verification_field_name(attribute_id))
  if label ~= nil then
    clear_verification_pending(device, attribute_id)
  end
  return label
end

local function log_verified_value(device, attribute_id, value)
  local label = consume_verification_pending(device, attribute_id)
  if label ~= nil then
    log.info(string.format(
      "[FP300][%s] verified %s (0x%04X) = %s",
      device.label or device.id or "?",
      tostring(label),
      attribute_id,
      format_value_for_log(value)
    ))
  end
end

local function log_verification_timeout(device, attribute_id, label, token)
  local timeout_field_name = verification_timeout_field_name(attribute_id)
  local token_field_name = verification_token_field_name(attribute_id)
  local pending_label = get_field_value(device, timeout_field_name)
  local pending_token = get_field_value(device, token_field_name)

  if pending_label ~= nil and pending_label == label and pending_token == token then
    clear_verification_pending(device, attribute_id)
    log.warn(string.format(
      "[FP300][%s] verification timed out for %s (0x%04X); no read/report received",
      device.label or device.id or "?",
      tostring(label),
      attribute_id
    ))
  end
end

local function should_skip_write(device, attribute_id, value, force_write)
  if force_write then
    return false
  end

  local pending_value = get_field_value(device, pending_requested_field_name(attribute_id))
  if pending_value ~= nil and pending_value == value then
    return true
  end

  local last_requested = get_field_value(device, last_requested_field_name(attribute_id))
  if last_requested ~= nil and pending_value == nil and last_requested == value then
    return true
  end

  return false
end

local function record_last_requested_value(device, attribute_id, value)
  device:set_field(last_requested_field_name(attribute_id), value, { persist = false })
end

local function get_pref_number(device, pref_id, default)
  local prefs = device.preferences or {}
  local value = tonumber(prefs[pref_id])
  if value == nil then
    return default
  end
  return value
end

local function clamp_number(value, min_value, max_value)
  if value == nil then return nil end
  return utils.clamp_value(value, min_value, max_value)
end

local function clamp_battery_percentage(millivolts)
  if millivolts == nil then return nil end
  local pct = math.floor((((millivolts - 2850) / (3000 - 2850)) * 100) + 0.5)
  return clamp_number(pct, 0, 100)
end

local function parse_aqara_attribute_report(raw)
  local parsed = {}
  if type(raw) ~= "string" then
    return parsed
  end

  local index = 1
  while index + 1 <= #raw do
    local tag = raw:byte(index)
    local zcl_type = raw:byte(index + 1)
    index = index + 2

    local length = nil
    if zcl_type == 0x10 or zcl_type == 0x18 or zcl_type == 0x20 then
      length = 1
    elseif zcl_type == 0x21 or zcl_type == 0x29 then
      length = 2
    elseif zcl_type == 0x23 or zcl_type == 0x2B then
      length = 4
    elseif zcl_type == 0x42 then
      if index > #raw then break end
      length = raw:byte(index)
      index = index + 1
    else
      break
    end

    if length == nil or index + length - 1 > #raw then
      break
    end

    if tag == 0x17 and zcl_type == 0x21 then
      local low = raw:byte(index) or 0
      local high = raw:byte(index + 1) or 0
      parsed.battery_mv = low + (high << 8)
    elseif tag == 0x18 and zcl_type == 0x20 then
      parsed.battery_pct = raw:byte(index)
    elseif tag == 0x18 and zcl_type == 0x21 then
      local low = raw:byte(index) or 0
      local high = raw:byte(index + 1) or 0
      parsed.battery_pct = low + (high << 8)
    end

    index = index + length
  end

  return parsed
end

local function read_custom_attribute(device, attribute_id)
  local message = cluster_base.read_attribute(
    device,
    data_types.ClusterId(AQARA_CLUSTER_ID),
    data_types.AttributeId(attribute_id)
  )
  message.body.zcl_header.frame_ctrl:set_mfg_specific()
  message.body.zcl_header.mfg_code = data_types.validate_or_build_type(AQARA_MFG_CODE, data_types.Uint16, "mfg_code")
  return message
end

local function write_custom_attribute(device, attribute_id, data_type, value)
  local data = data_types.validate_or_build_type(value, data_type)
  local message = cluster_base.write_attribute(
    device,
    data_types.ClusterId(AQARA_CLUSTER_ID),
    data_types.AttributeId(attribute_id),
    data
  )
  message.body.zcl_header.frame_ctrl:set_mfg_specific()
  message.body.zcl_header.mfg_code = data_types.validate_or_build_type(AQARA_MFG_CODE, data_types.Uint16, "mfg_code")
  return message
end

local function write_and_verify_custom_attribute(device, attribute_id, data_type, value, label, force_write)
  if should_skip_write(device, attribute_id, value, force_write) then
    return false
  end

  local verify_label = label or string.format("0x%04X", attribute_id)
  local write_sent = safe_build_send(device, verify_label, function()
    return write_custom_attribute(device, attribute_id, data_type, value)
  end)

  if not write_sent then
    return false
  end

  record_last_requested_value(device, attribute_id, value)
  local verify_token, stored_label = mark_verification_pending(device, attribute_id, verify_label, value)

  log.info(string.format(
    "[FP300][%s] queued verification for %s (0x%04X)",
    device.label or device.id or "?",
    tostring(stored_label),
    attribute_id
  ))

  device.thread:call_with_delay(1, function()
    if get_field_value(device, verification_token_field_name(attribute_id)) ~= verify_token then
      return
    end

    log.info(string.format(
      "[FP300][%s] sending readback for %s (0x%04X)",
      device.label or device.id or "?",
      tostring(stored_label),
      attribute_id
    ))
    safe_build_send(device, stored_label .. " readback", function()
      return read_custom_attribute(device, attribute_id)
    end)
  end)

  device.thread:call_with_delay(4, function()
    log_verification_timeout(device, attribute_id, stored_label, verify_token)
  end)

  return true
end


local function send_action_write(device, attribute_id, data_type, value, label)
  local action_label = label or string.format("0x%04X", attribute_id)
  local sent = safe_build_send(device, action_label, function()
    return write_custom_attribute(device, attribute_id, data_type, value)
  end)

  if sent then
    log.info(string.format(
      "[FP300][%s] sent action %s (0x%04X)",
      device.label or device.id or "?",
      tostring(action_label),
      attribute_id
    ))
  end

  return sent
end

local function refresh_all(device)
  for _, builder in ipairs(STANDARD_REFRESHES) do
    safe_send(device, builder(device), "standard refresh")
  end
  for _, attr_id in ipairs(CUSTOM_REFRESH_ATTRS) do
    safe_build_send(device, string.format("read 0x%04X", attr_id), function() return read_custom_attribute(device, attr_id) end)
  end
end

local function handle_temperature(_, device, value)
  local raw = tonumber(raw_value(value))
  if raw == nil then return end
  local c = (raw / 100.0) + get_pref_number(device, "tempOffset", 0)
  c = math.floor((c * 100) + 0.5) / 100
  device:emit_event(capabilities.temperatureMeasurement.temperature({ value = c, unit = "C" }))
end

local function handle_humidity(_, device, value)
  local raw = tonumber(raw_value(value))
  if raw == nil then return end
  local pct = (raw / 100.0) + get_pref_number(device, "humidityOffset", 0)
  pct = clamp_number(math.floor(pct + 0.5), 0, 100)
  device:emit_event(capabilities.relativeHumidityMeasurement.humidity(pct))
end

local function handle_illuminance(_, device, value)
  local raw = tonumber(raw_value(value))
  if raw == nil then return end
  local lux = math.floor((raw / 1000.0) + 0.5)
  device:emit_event(capabilities.illuminanceMeasurement.illuminance(lux))
end

local function handle_presence(_, device, value)
  local present = raw_value(value)
  local is_present = (present == true or present == 1)
  device:emit_event(capabilities.presenceSensor.presence(is_present and "present" or "not present"))
end

local function handle_pir_detection(_, device, value)
  local active = raw_value(value)
  local is_active = (active == true or active == 1)
  device:emit_event(capabilities.motionSensor.motion(is_active and "active" or "inactive"))
end

local function handle_battery(_, device, value)
  local millivolts = tonumber(raw_value(value))
  if millivolts == nil then return end
  local pct = clamp_battery_percentage(millivolts)
  if pct ~= nil then
    device:emit_event(capabilities.battery.battery(pct))
  end
end

local function handle_aqara_attribute_report(_, device, value)
  local parsed = parse_aqara_attribute_report(raw_value(value))
  if parsed.battery_mv ~= nil then
    handle_battery(nil, device, { value = parsed.battery_mv })
  elseif parsed.battery_pct ~= nil then
    local pct = clamp_number(math.floor(parsed.battery_pct + 0.5), 0, 100)
    if pct ~= nil then
      device:emit_event(capabilities.battery.battery(pct))
    end
  end
end

local function verification_only_handler(attribute_id)
  return function(_, device, value)
    log_verified_value(device, attribute_id, value)
  end
end

local function handle_prevent_leave(_, device, value)
  log_verified_value(device, ATTR.PREVENT_LEAVE, value)
  local current = raw_value(value)
  if current == false or current == 0 then
    safe_build_send(device, "prevent-leave", function() return write_custom_attribute(device, ATTR.PREVENT_LEAVE, data_types.Boolean, true) end)
  end
end

local function handle_target_distance(_, device, value)
  local raw = tonumber(raw_value(value))
  if raw == nil then
    return
  end

  local meters = math.floor(((raw / 100.0) * 100) + 0.5) / 100
  local previous = get_field_value(device, FIELDS.TARGET_DISTANCE_METERS)
  device:set_field(FIELDS.TARGET_DISTANCE_METERS, meters, { persist = false })
  log_verified_value(device, ATTR.TARGET_DISTANCE, value)

  if target_distance_cap ~= nil and target_distance_cap.distance ~= nil then
    device:emit_event(target_distance_cap.distance({ value = meters, unit = "m" }))
  end

  if previous == nil or previous ~= meters then
    log.info(string.format(
      "[FP300][%s] target distance = %.2f m",
      device.label or device.id or "?",
      meters
    ))
  end
end

local function handle_detection_range_raw(_, device, value)
  log_verified_value(device, ATTR.DETECTION_RANGE_RAW, value)
  local raw = raw_value(value)

  if type(raw) == "string" then
    device:set_field(FIELDS.DETECTION_RANGE_RAW, raw, { persist = false })

    if #raw >= 5 then
      local prefix = (raw:byte(1) or 0) + ((raw:byte(2) or 0) << 8)
      local mask = (raw:byte(3) or 0) + ((raw:byte(4) or 0) << 8) + ((raw:byte(5) or 0) << 16)
      device:set_field(FIELDS.DETECTION_RANGE_PREFIX, prefix, { persist = true })
      device:set_field(FIELDS.DETECTION_RANGE_MASK, mask, { persist = true })
    elseif #raw >= 3 then
      local legacy_mask = (raw:byte(1) or 0) + ((raw:byte(2) or 0) << 8) + ((raw:byte(3) or 0) << 16)
      device:set_field(FIELDS.DETECTION_RANGE_MASK, legacy_mask, { persist = true })
    end
  elseif type(raw) == "number" then
    device:set_field(FIELDS.DETECTION_RANGE_MASK, raw, { persist = true })
  end
end

local function handle_led_schedule(_, device, value)
  log_verified_value(device, ATTR.LED_SCHEDULE_RAW, value)
  local raw_number = tonumber(raw_value(value))
  if raw_number ~= nil then
    device:set_field(FIELDS.LED_SCHEDULE_RAW, raw_number, { persist = true })
  end
end

local function encode_time_string(value)
  if type(value) ~= "string" then return nil end
  local hours, minutes = string.match(value, "^(%d%d):(%d%d)$")
  hours = tonumber(hours)
  minutes = tonumber(minutes)
  if hours == nil or minutes == nil then return nil end
  if hours < 0 or hours > 23 or minutes < 0 or minutes > 59 then return nil end
  return hours, minutes
end

local function encode_led_schedule(start_time, end_time)
  local start_hour, start_min = encode_time_string(start_time)
  local end_hour, end_min = encode_time_string(end_time)
  if start_hour == nil or end_hour == nil then return nil end
  return start_hour | (start_min << 8) | (end_hour << 16) | (end_min << 24)
end


local function build_detection_range_raw(mask, prefix)
  local safe_prefix = clamp_number(tonumber(prefix) or 0x0300, 0, 0xFFFF) or 0x0300
  local safe_mask = clamp_number(tonumber(mask) or 0xFFFFFF, 0, 0xFFFFFF) or 0xFFFFFF

  local b0 = safe_prefix & 0xFF
  local b1 = (safe_prefix >> 8) & 0xFF
  local b2 = safe_mask & 0xFF
  local b3 = (safe_mask >> 8) & 0xFF
  local b4 = (safe_mask >> 16) & 0xFF

  return string.char(b0, b1, b2, b3, b4), safe_prefix, safe_mask
end

local function get_detection_range_mask_from_preferences(device)
  local old_mask = get_field_value(device, FIELDS.DETECTION_RANGE_MASK) or 0
  local prefs = device.preferences or {}
  local bands = {
    prefs.fp300Range0to1,
    prefs.fp300Range1to2,
    prefs.fp300Range2to3,
    prefs.fp300Range3to4,
    prefs.fp300Range4to5,
    prefs.fp300Range5to6,
  }

  local new_mask = old_mask
  for band_index, enabled in ipairs(bands) do
    local group_shift = (band_index - 1) * 4
    local band_bits = 0x0F << group_shift
    if enabled then
      new_mask = (new_mask | band_bits)
    else
      new_mask = (new_mask & (~band_bits))
    end
  end
  return new_mask & 0xFFFFFF
end

local function write_detection_range_mask(device, mask, force_write)
  local current_prefix = get_field_number(device, FIELDS.DETECTION_RANGE_PREFIX, 0x0300) or 0x0300
  local raw_bytes, safe_prefix, safe_mask = build_detection_range_raw(mask, current_prefix)

  if write_and_verify_custom_attribute(device, ATTR.DETECTION_RANGE_RAW, data_types.OctetString, raw_bytes, "detection range", force_write) then
    device:set_field(FIELDS.DETECTION_RANGE_PREFIX, safe_prefix, { persist = true })
    device:set_field(FIELDS.DETECTION_RANGE_MASK, safe_mask, { persist = true })
    device:set_field(FIELDS.DETECTION_RANGE_RAW, raw_bytes, { persist = false })
  end
end

local function apply_preferences(device, old_prefs, force_all)
  local prefs = device.preferences or {}
  old_prefs = old_prefs or {}

  local function changed(pref_id)
    return force_all or old_prefs[pref_id] ~= prefs[pref_id]
  end

  if prefs.fp300DetectionRangeMask ~= nil and changed("fp300DetectionRangeMask") then
    local mask = clamp_number(tonumber(prefs.fp300DetectionRangeMask) or 0, 0, 0xFFFFFF)
    write_detection_range_mask(device, mask, force_all)
  elseif force_all
      or changed("fp300Range0to1")
      or changed("fp300Range1to2")
      or changed("fp300Range2to3")
      or changed("fp300Range3to4")
      or changed("fp300Range4to5")
      or changed("fp300Range5to6") then
    write_detection_range_mask(device, get_detection_range_mask_from_preferences(device), force_all)
  end

  if force_all or changed("fp300LedScheduleStart") or changed("fp300LedScheduleEnd") then
    local encoded = encode_led_schedule(prefs.fp300LedScheduleStart, prefs.fp300LedScheduleEnd)
    if encoded ~= nil then
      if write_and_verify_custom_attribute(device, ATTR.LED_SCHEDULE_RAW, data_types.Uint32, encoded, "LED schedule", force_all) then
        device:set_field(FIELDS.LED_SCHEDULE_RAW, encoded, { persist = true })
      end
    else
      log.warn(string.format("[FP300][%s] invalid LED schedule '%s' -> '%s'", device.label or device.id or "?", tostring(prefs.fp300LedScheduleStart), tostring(prefs.fp300LedScheduleEnd)))
    end
  end

  if changed("fp300PresenceMode") then
    local map = { both = 0, mmwave = 1, pir = 2 }
    local value = map[prefs.fp300PresenceMode]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.PRESENCE_DETECTION_OPTIONS, data_types.Uint8, value, "presence mode", force_all)
    end
  end

  if changed("fp300MotionSensitivity") then
    local map = { low = 1, medium = 2, high = 3 }
    local value = map[prefs.fp300MotionSensitivity]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.MOTION_SENSITIVITY, data_types.Uint8, value, "motion sensitivity", force_all)
    end
  end

  if changed("fp300AbsenceDelay") then
    local value = clamp_number(tonumber(prefs.fp300AbsenceDelay) or 10, 10, 300)
    write_and_verify_custom_attribute(device, ATTR.ABSENCE_DELAY_TIMER, data_types.Uint32, value, "absence delay", force_all)
  end

  if changed("fp300PirInterval") then
    local value = clamp_number(tonumber(prefs.fp300PirInterval) or 2, 2, 300)
    write_and_verify_custom_attribute(device, ATTR.PIR_DETECTION_INTERVAL, data_types.Uint16, value, "pir interval", force_all)
  end

  if changed("fp300AiAdaptive") then
    write_and_verify_custom_attribute(device, ATTR.AI_ADAPTIVE_SENSITIVITY, data_types.Uint8, prefs.fp300AiAdaptive and 1 or 0, "AI adaptive", force_all)
  end

  if changed("fp300AiInterference") then
    write_and_verify_custom_attribute(device, ATTR.AI_INTERFERENCE_IDENT, data_types.Uint8, prefs.fp300AiInterference and 1 or 0, "AI interference", force_all)
  end

  if changed("fp300TempHumSampling") then
    local map = { off = 0, low = 1, medium = 2, high = 3, custom = 4 }
    local value = map[prefs.fp300TempHumSampling]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.TEMP_HUMIDITY_SAMPLING, data_types.Uint8, value, "temp/hum sampling", force_all)
    end
  end

  if changed("fp300TempHumSamplePeriod") then
    local value = clamp_number(tonumber(prefs.fp300TempHumSamplePeriod) or 0.5, 0.5, 3600)
    write_and_verify_custom_attribute(device, ATTR.TEMP_HUMIDITY_SAMPLING_PERIOD, data_types.Uint32, math.floor((value * 1000) + 0.5), "temp/hum sample period", force_all)
  end

  if changed("fp300TempRptInterval") then
    local value = clamp_number(tonumber(prefs.fp300TempRptInterval) or 600, 600, 3600)
    write_and_verify_custom_attribute(device, ATTR.TEMP_REPORTING_INTERVAL, data_types.Uint32, math.floor((value * 1000) + 0.5), "temp report interval", force_all)
  end

  if changed("fp300TempRptThreshold") then
    local value = clamp_number(tonumber(prefs.fp300TempRptThreshold) or 0.2, 0.2, 3.0)
    write_and_verify_custom_attribute(device, ATTR.TEMP_REPORTING_THRESHOLD, data_types.Uint16, math.floor((value * 100) + 0.5), "temp report threshold", force_all)
  end

  if changed("fp300TempReportingMode") then
    local map = { threshold = 1, interval = 2, both = 3 }
    local value = map[prefs.fp300TempReportingMode]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.TEMP_REPORTING_MODE, data_types.Uint8, value, "temp report mode", force_all)
    end
  end

  if changed("fp300HumRptInterval") then
    local value = clamp_number(tonumber(prefs.fp300HumRptInterval) or 600, 600, 3600)
    write_and_verify_custom_attribute(device, ATTR.HUMIDITY_REPORTING_INTERVAL, data_types.Uint32, math.floor((value * 1000) + 0.5), "humidity report interval", force_all)
  end

  if changed("fp300HumRptThreshold") then
    local value = clamp_number(tonumber(prefs.fp300HumRptThreshold) or 2.0, 2.0, 15.0)
    write_and_verify_custom_attribute(device, ATTR.HUMIDITY_REPORTING_THRESHOLD, data_types.Uint16, math.floor((value * 100) + 0.5), "humidity report threshold", force_all)
  end

  if changed("fp300HumRptMode") then
    local map = { threshold = 1, interval = 2, both = 3 }
    local value = map[prefs.fp300HumRptMode]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.HUMIDITY_REPORTING_MODE, data_types.Uint8, value, "humidity report mode", force_all)
    end
  end

  if changed("fp300LightSampling") then
    local map = { off = 0, low = 1, medium = 2, high = 3, custom = 4 }
    local value = map[prefs.fp300LightSampling]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.LIGHT_SAMPLING, data_types.Uint8, value, "light sampling", force_all)
    end
  end

  if changed("fp300LightSamplingPeriod") then
    local value = clamp_number(tonumber(prefs.fp300LightSamplingPeriod) or 0.5, 0.5, 3600)
    write_and_verify_custom_attribute(device, ATTR.LIGHT_SAMPLING_PERIOD, data_types.Uint32, math.floor((value * 1000) + 0.5), "light sampling period", force_all)
  end

  if changed("fp300LightRptInterval") then
    local value = clamp_number(tonumber(prefs.fp300LightRptInterval) or 20, 20, 3600)
    write_and_verify_custom_attribute(device, ATTR.LIGHT_REPORTING_INTERVAL, data_types.Uint32, math.floor((value * 1000) + 0.5), "light report interval", force_all)
  end

  if changed("fp300LightRptThreshold") then
    local value = clamp_number(tonumber(prefs.fp300LightRptThreshold) or 3.0, 3.0, 20.0)
    write_and_verify_custom_attribute(device, ATTR.LIGHT_REPORTING_THRESHOLD, data_types.Uint16, math.floor((value * 100) + 0.5), "light report threshold", force_all)
  end

  if changed("fp300LightReportingMode") then
    local map = { threshold = 1, interval = 2, both = 3 }
    local value = map[prefs.fp300LightReportingMode]
    if value ~= nil then
      write_and_verify_custom_attribute(device, ATTR.LIGHT_REPORTING_MODE, data_types.Uint8, value, "light report mode", force_all)
    end
  end

  if changed("fp300LedDisabledNight") then
    write_and_verify_custom_attribute(device, ATTR.LED_DISABLED_NIGHT, data_types.Boolean, prefs.fp300LedDisabledNight and true or false, "LED disabled at night", force_all)
  end

  if changed("fp300TrackDist") and prefs.fp300TrackDist == true then
    local track_sent = send_action_write(device, ATTR.TRACK_TARGET_DISTANCE, data_types.Uint8, 1, "track target distance")
    if track_sent then
      device.thread:call_with_delay(1, function()
        safe_build_send(device, "read target distance", function()
          return read_custom_attribute(device, ATTR.TARGET_DISTANCE)
        end)
      end)
      device.thread:call_with_delay(3, function()
        safe_build_send(device, "read target distance", function()
          return read_custom_attribute(device, ATTR.TARGET_DISTANCE)
        end)
      end)
    end
  end

  if changed("fp300SpatialLearn") and prefs.fp300SpatialLearn == true then
    send_action_write(device, ATTR.SPATIAL_LEARNING, data_types.Uint8, 1, "spatial learning")
  end

  if changed("fp300RestartDevice") and prefs.fp300RestartDevice == true then
    send_action_write(device, ATTR.RESTART_DEVICE, data_types.Boolean, true, "restart device")
  end
end

local function added_handler(_, device)
  device:emit_event(capabilities.presenceSensor.presence("not present"))
  device:emit_event(capabilities.motionSensor.motion("inactive"))
end

local function init_handler(_, device)
  if get_field_value(device, FIELDS.DETECTION_RANGE_MASK) == nil then
    device:set_field(FIELDS.DETECTION_RANGE_MASK, 0xFFFFFF, { persist = true })
  end
  if get_field_value(device, FIELDS.DETECTION_RANGE_PREFIX) == nil then
    device:set_field(FIELDS.DETECTION_RANGE_PREFIX, 0x0300, { persist = true })
  end
end

local function do_configure(driver, device)
  local hub_eui = driver.environment_info and driver.environment_info.hub_zigbee_eui
  if hub_eui then
    safe_send(device, device_management.build_bind_request(device, TemperatureMeasurement.ID, hub_eui), "bind temp")
    safe_send(device, device_management.build_bind_request(device, RelativeHumidity.ID, hub_eui), "bind humidity")
    safe_send(device, device_management.build_bind_request(device, IlluminanceMeasurement.ID, hub_eui), "bind illuminance")
  end

  safe_send(device, TemperatureMeasurement.attributes.MeasuredValue:configure_reporting(device, 30, 300, 20), "cfg temp")
  safe_send(device, RelativeHumidity.attributes.MeasuredValue:configure_reporting(device, 30, 300, 100), "cfg humidity")
  safe_send(device, IlluminanceMeasurement.attributes.MeasuredValue:configure_reporting(device, 30, 300, 1000), "cfg illuminance")

  safe_build_send(device, "prevent-leave", function() return write_custom_attribute(device, ATTR.PREVENT_LEAVE, data_types.Boolean, true) end)
  apply_preferences(device, {}, true)

  device.thread:call_with_delay(4, function()
    refresh_all(device)
  end)
end

local function refresh_handler(_, device, _)
  refresh_all(device)
end

local function info_changed(_, device, _, args)
  local old_prefs = {}
  if args and args.old_st_store and args.old_st_store.preferences then
    old_prefs = args.old_st_store.preferences
  end

  local generation = (get_field_number(device, FIELDS.INFO_CHANGED_GENERATION, 0) or 0) + 1
  device:set_field(FIELDS.INFO_CHANGED_GENERATION, generation, { persist = false })

  device.thread:call_with_delay(INFO_CHANGED_DEBOUNCE_SECONDS, function()
    if get_field_value(device, FIELDS.INFO_CHANGED_GENERATION) ~= generation then
      return
    end

    apply_preferences(device, old_prefs, false)
  end)
end

local supported_capabilities = {
  capabilities.presenceSensor,
  capabilities.motionSensor,
  capabilities.battery,
  capabilities.temperatureMeasurement,
  capabilities.relativeHumidityMeasurement,
  capabilities.illuminanceMeasurement,
  capabilities.refresh,
}

if target_distance_cap ~= nil then
  table.insert(supported_capabilities, target_distance_cap)
end

local fp300_driver_template = {
  supported_capabilities = supported_capabilities,
  capability_handlers = {
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = refresh_handler,
    },
  },
  zigbee_handlers = {
    attr = {
      [TemperatureMeasurement.ID] = {
        [TemperatureMeasurement.attributes.MeasuredValue.ID] = handle_temperature,
      },
      [RelativeHumidity.ID] = {
        [RelativeHumidity.attributes.MeasuredValue.ID] = handle_humidity,
      },
      [IlluminanceMeasurement.ID] = {
        [IlluminanceMeasurement.attributes.MeasuredValue.ID] = handle_illuminance,
      },
      [AQARA_CLUSTER_ID] = {
        [ATTR.AQARA_ATTRIBUTE_REPORT] = handle_aqara_attribute_report,
        [ATTR.PREVENT_LEAVE] = handle_prevent_leave,
        [ATTR.BATTERY_VOLTAGE] = handle_battery,
        [ATTR.PRESENCE] = handle_presence,
        [ATTR.PIR_DETECTION] = handle_pir_detection,
        [ATTR.MOTION_SENSITIVITY] = verification_only_handler(ATTR.MOTION_SENSITIVITY),
        [ATTR.PIR_DETECTION_INTERVAL] = verification_only_handler(ATTR.PIR_DETECTION_INTERVAL),
        [ATTR.AI_ADAPTIVE_SENSITIVITY] = verification_only_handler(ATTR.AI_ADAPTIVE_SENSITIVITY),
        [ATTR.AI_INTERFERENCE_IDENT] = verification_only_handler(ATTR.AI_INTERFERENCE_IDENT),
        [ATTR.TEMP_HUMIDITY_SAMPLING] = verification_only_handler(ATTR.TEMP_HUMIDITY_SAMPLING),
        [ATTR.TEMP_HUMIDITY_SAMPLING_PERIOD] = verification_only_handler(ATTR.TEMP_HUMIDITY_SAMPLING_PERIOD),
        [ATTR.TEMP_REPORTING_INTERVAL] = verification_only_handler(ATTR.TEMP_REPORTING_INTERVAL),
        [ATTR.TEMP_REPORTING_THRESHOLD] = verification_only_handler(ATTR.TEMP_REPORTING_THRESHOLD),
        [ATTR.TEMP_REPORTING_MODE] = verification_only_handler(ATTR.TEMP_REPORTING_MODE),
        [ATTR.HUMIDITY_REPORTING_INTERVAL] = verification_only_handler(ATTR.HUMIDITY_REPORTING_INTERVAL),
        [ATTR.HUMIDITY_REPORTING_THRESHOLD] = verification_only_handler(ATTR.HUMIDITY_REPORTING_THRESHOLD),
        [ATTR.HUMIDITY_REPORTING_MODE] = verification_only_handler(ATTR.HUMIDITY_REPORTING_MODE),
        [ATTR.LIGHT_SAMPLING] = verification_only_handler(ATTR.LIGHT_SAMPLING),
        [ATTR.LIGHT_SAMPLING_PERIOD] = verification_only_handler(ATTR.LIGHT_SAMPLING_PERIOD),
        [ATTR.LIGHT_REPORTING_INTERVAL] = verification_only_handler(ATTR.LIGHT_REPORTING_INTERVAL),
        [ATTR.LIGHT_REPORTING_THRESHOLD] = verification_only_handler(ATTR.LIGHT_REPORTING_THRESHOLD),
        [ATTR.LIGHT_REPORTING_MODE] = verification_only_handler(ATTR.LIGHT_REPORTING_MODE),
        [ATTR.ABSENCE_DELAY_TIMER] = verification_only_handler(ATTR.ABSENCE_DELAY_TIMER),
        [ATTR.PRESENCE_DETECTION_OPTIONS] = verification_only_handler(ATTR.PRESENCE_DETECTION_OPTIONS),
        [ATTR.TARGET_DISTANCE] = handle_target_distance,
        [ATTR.DETECTION_RANGE_RAW] = handle_detection_range_raw,
        [ATTR.LED_DISABLED_NIGHT] = verification_only_handler(ATTR.LED_DISABLED_NIGHT),
        [ATTR.LED_SCHEDULE_RAW] = handle_led_schedule,
      },
    },
  },
  lifecycle_handlers = {
    init = init_handler,
    added = added_handler,
    doConfigure = do_configure,
    infoChanged = info_changed,
  },
  can_handle = can_handle_fp300,
  health_check = false,
  shared_device_thread_enabled = true,
}

local driver = ZigbeeDriver("aqara-fp300-zigbee", fp300_driver_template)
driver:run()
