local capabilities = require "st.capabilities"
local cluster_base = require "st.zigbee.cluster_base"
local clusters = require "st.zigbee.zcl.clusters"
local data_types = require "st.zigbee.data_types"
local zigbee_constants = require "st.zigbee.constants"
local log = require "log"

local OnOff = clusters.OnOff
local AnalogInput = clusters.AnalogInput
local SimpleMetering = clusters.SimpleMetering
local ElectricalMeasurement = clusters.ElectricalMeasurement
local TemperatureMeasurement = clusters.TemperatureMeasurement

local MFG_CODE = 0x115F
local AQARA_CLUSTER_ID = 0xFCC0

-- Endpoint layout from public ZHA diagnostics for lumi.plug.aeu001:
-- EP1: Basic/OnOff/Temperature/SimpleMetering/ElectricalMeasurement/0xFCC0
-- EP2: OnOff, actual controllable outlet switch in public reports
-- EP21: AnalogInput power path
local CONTROL_ENDPOINT = 2
local FALLBACK_CONTROL_ENDPOINT = 1
local METERING_ENDPOINT = 1
local ELECTRICAL_ENDPOINT = 1
local TEMPERATURE_ENDPOINT = 1
local ANALOG_POWER_ENDPOINT = 21

-- Aqara manufacturer-specific 0xFCC0 attributes from public ZHA quirk work.
local ATTR_BUTTON_LOCK = 0x0200
local ATTR_CHARGING_PROTECTION = 0x0202
local ATTR_LED_INDICATOR = 0x0203
local ATTR_CHARGING_LIMIT = 0x0206
local ATTR_OVERLOAD_PROTECTION = 0x020B
local ATTR_POWER_ON_BEHAVIOR = 0x0517

local FIELD_ANALOG_POWER_SEEN_AT = "aqara_h2_outlet_analog_power_seen_at"
local FIELD_ELEC_POWER_MULT = "aqara_h2_outlet_elec_power_mult"
local FIELD_ELEC_POWER_DIV = "aqara_h2_outlet_elec_power_div"
local FIELD_ELEC_VOLTAGE_MULT = "aqara_h2_outlet_elec_voltage_mult"
local FIELD_ELEC_VOLTAGE_DIV = "aqara_h2_outlet_elec_voltage_div"
local FIELD_ELEC_CURRENT_MULT = "aqara_h2_outlet_elec_current_mult"
local FIELD_ELEC_CURRENT_DIV = "aqara_h2_outlet_elec_current_div"
local FIELD_LAST_ENERGY = "aqara_h2_outlet_last_energy"
local FIELD_LAST_AGGREGATE_TEMP_AT = "aqara_h2_outlet_last_aggregate_temp_at"
local ANALOG_POWER_FRESH_SECONDS = 720
local AGGREGATE_TEMP_PREFER_SECONDS = 30

local POWER_ON_BEHAVIOR_VALUES = {
  on = 0x00,
  previous = 0x01,
  off = 0x02,
  inverted = 0x03,
}

local CONFIGURED_ATTRIBUTES = {
  {
    cluster = OnOff.ID,
    attribute = OnOff.attributes.OnOff.ID,
    minimum_interval = 0,
    maximum_interval = 300,
    data_type = OnOff.attributes.OnOff.base_type,
  },
  {
    cluster = AnalogInput.ID,
    attribute = AnalogInput.attributes.PresentValue.ID,
    minimum_interval = 0,
    maximum_interval = 600,
    data_type = AnalogInput.attributes.PresentValue.base_type,
    reportable_change = data_types.SinglePrecisionFloat(0, 0, 0),
  },
  {
    cluster = SimpleMetering.ID,
    attribute = SimpleMetering.attributes.CurrentSummationDelivered.ID,
    minimum_interval = 30,
    maximum_interval = 3600,
    data_type = SimpleMetering.attributes.CurrentSummationDelivered.base_type,
    reportable_change = 1,
  },
  {
    cluster = ElectricalMeasurement.ID,
    attribute = ElectricalMeasurement.attributes.ActivePower.ID,
    minimum_interval = 5,
    maximum_interval = 65535,
    data_type = ElectricalMeasurement.attributes.ActivePower.base_type,
    reportable_change = 5,
  },
  {
    cluster = ElectricalMeasurement.ID,
    attribute = ElectricalMeasurement.attributes.RMSVoltage.ID,
    minimum_interval = 30,
    maximum_interval = 600,
    data_type = ElectricalMeasurement.attributes.RMSVoltage.base_type,
    reportable_change = 1,
  },
  {
    cluster = ElectricalMeasurement.ID,
    attribute = ElectricalMeasurement.attributes.RMSCurrent.ID,
    minimum_interval = 30,
    maximum_interval = 600,
    data_type = ElectricalMeasurement.attributes.RMSCurrent.base_type,
    reportable_change = 10,
  },
}

local function round(value, places)
  local power = 10 ^ (places or 0)
  return math.floor((value * power) + 0.5) / power
end

local function clamp(value, min, max)
  if value < min then return min end
  if value > max then return max end
  return value
end

local function simple_value(value)
  if value == nil then return nil end
  if type(value) == "table" and value.value ~= nil then
    return value.value
  end
  return value
end

local function number_to_single_precision_float(number)
  local n = tonumber(number) or 0
  if n == 0 then
    -- Zigbee FloatABC represents values as (1 + mantissa) * 2 ^ exponent,
    -- with sign stored separately. This zero fallback should not normally be
    -- used by the clamped outlet preferences, but keeps the helper total.
    return data_types.SinglePrecisionFloat(0, -127, 0)
  end

  local sign = 0
  if n < 0 then
    sign = 1
    n = -n
  end

  local exponent = math.floor(math.log(n) / math.log(2) + 1e-10)
  local mantissa = (n / (2 ^ exponent)) - 1
  if mantissa >= 1.0 then mantissa = mantissa - 1e-10 end
  return data_types.SinglePrecisionFloat(sign, exponent, mantissa)
end

local function send_to_endpoint(device, zigbee_message, endpoint)
  if endpoint ~= nil then
    device:send(zigbee_message:to_endpoint(endpoint))
  else
    device:send(zigbee_message)
  end
end

local function read_mfg_attr(device, attr_id)
  local msg = cluster_base.read_manufacturer_specific_attribute(
    device,
    AQARA_CLUSTER_ID,
    attr_id,
    MFG_CODE
  )
  send_to_endpoint(device, msg, METERING_ENDPOINT)
end

local function write_mfg_attr(device, attr_id, data_type, value)
  local msg = cluster_base.write_manufacturer_specific_attribute(
    device,
    AQARA_CLUSTER_ID,
    attr_id,
    MFG_CODE,
    data_type,
    value
  )
  send_to_endpoint(device, msg, METERING_ENDPOINT)
end

local PREFERENCES = {
  ledIndicator = {
    attr = ATTR_LED_INDICATOR,
    data_type = data_types.Boolean,
    encode = function(raw) return data_types.Boolean(raw == true) end,
  },
  powerOnBehavior = {
    attr = ATTR_POWER_ON_BEHAVIOR,
    data_type = data_types.Uint8,
    encode = function(raw) return data_types.Uint8(POWER_ON_BEHAVIOR_VALUES[raw] or POWER_ON_BEHAVIOR_VALUES.previous) end,
  },
  -- ZHA exposes this as a switch with force_inverted=True. The SmartThings
  -- preference uses the user-facing meaning: true = physical button locked.
  buttonLock = {
    attr = ATTR_BUTTON_LOCK,
    data_type = data_types.Uint8,
    encode = function(raw) return data_types.Uint8(raw and 0 or 1) end,
  },
  chargingProtection = {
    attr = ATTR_CHARGING_PROTECTION,
    data_type = data_types.Boolean,
    encode = function(raw) return data_types.Boolean(raw == true) end,
  },
  chargingLimit = {
    attr = ATTR_CHARGING_LIMIT,
    data_type = data_types.SinglePrecisionFloat,
    encode = function(raw) return number_to_single_precision_float(clamp(tonumber(raw) or 2, 0.1, 2)) end,
  },
  overloadProtection = {
    attr = ATTR_OVERLOAD_PROTECTION,
    data_type = data_types.SinglePrecisionFloat,
    encode = function(raw) return number_to_single_precision_float(clamp(tonumber(raw) or 3840, 100, 3840)) end,
  },
}

-- Driver-side defaults are used when the SmartThings preference value has not
-- been materialized yet. Profile defaults are UI metadata; writing these values
-- makes the physical outlet state deterministic after fresh join or driver switch.
local PREFERENCE_DEFAULTS = {
  ledIndicator = true,
  powerOnBehavior = "previous",
  buttonLock = false,
  chargingProtection = false,
  chargingLimit = 2,
  overloadProtection = 3840,
}

local function get_preference_old_value(args, preference_name)
  if args == nil or args.old_st_store == nil or args.old_st_store.preferences == nil then
    return nil
  end
  return args.old_st_store.preferences[preference_name]
end

local function preference_changed(old_value, new_value)
  if old_value == nil then
    return true
  end
  return old_value ~= new_value
end

local function effective_preference_value(device, pref_name)
  local value = nil
  if device.preferences ~= nil then
    value = device.preferences[pref_name]
  end
  if value == nil then
    return PREFERENCE_DEFAULTS[pref_name]
  end
  return value
end

local function write_preference_value(device, pref_name, pref, value, reason)
  if value == nil then
    log.debug(string.format("Skipping preference %s because no value/default is available", pref_name))
    return
  end

  log.info(string.format(
    "Applying preference %s=%s on %s endpoint %d attr 0x%04X (%s)",
    pref_name,
    tostring(value),
    device.label,
    METERING_ENDPOINT,
    pref.attr,
    reason or "preference update"
  ))
  write_mfg_attr(device, pref.attr, pref.data_type, pref.encode(value))
  log.debug(string.format("Reading back Aqara outlet attr 0x%04X after preference write", pref.attr))
  read_mfg_attr(device, pref.attr)
end

local function apply_preference_defaults(device, reason)
  for pref_name, pref in pairs(PREFERENCES) do
    local value = effective_preference_value(device, pref_name)
    write_preference_value(device, pref_name, pref, value, reason or "apply defaults")
  end
end

local function apply_preference_changes(device, args)
  for pref_name, pref in pairs(PREFERENCES) do
    local old_value = get_preference_old_value(args, pref_name)
    local new_value = device.preferences and device.preferences[pref_name] or nil
    if preference_changed(old_value, new_value) then
      write_preference_value(device, pref_name, pref, effective_preference_value(device, pref_name), "preference change")
    end
  end
end

local function initialize_scalars(device)
  if device:get_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY) == nil then
    device:set_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY, 1000, { persist = true })
  end
  if device:get_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY) == nil then
    device:set_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY, 1, { persist = true })
  end
  device:set_field(FIELD_ELEC_POWER_MULT, device:get_field(FIELD_ELEC_POWER_MULT) or 1, { persist = true })
  device:set_field(FIELD_ELEC_POWER_DIV, device:get_field(FIELD_ELEC_POWER_DIV) or 10, { persist = true })
  device:set_field(FIELD_ELEC_VOLTAGE_MULT, device:get_field(FIELD_ELEC_VOLTAGE_MULT) or 1, { persist = true })
  device:set_field(FIELD_ELEC_VOLTAGE_DIV, device:get_field(FIELD_ELEC_VOLTAGE_DIV) or 1, { persist = true })
  device:set_field(FIELD_ELEC_CURRENT_MULT, device:get_field(FIELD_ELEC_CURRENT_MULT) or 1, { persist = true })
  device:set_field(FIELD_ELEC_CURRENT_DIV, device:get_field(FIELD_ELEC_CURRENT_DIV) or 1000, { persist = true })
end

local function refresh_device_state(device)
  log.debug("Refreshing outlet state, metering, electrical values and Aqara preferences")
  send_to_endpoint(device, OnOff.attributes.OnOff:read(device), CONTROL_ENDPOINT)
  send_to_endpoint(device, OnOff.attributes.OnOff:read(device), FALLBACK_CONTROL_ENDPOINT)
  send_to_endpoint(device, AnalogInput.attributes.PresentValue:read(device), ANALOG_POWER_ENDPOINT)
  send_to_endpoint(device, SimpleMetering.attributes.CurrentSummationDelivered:read(device), METERING_ENDPOINT)
  send_to_endpoint(device, SimpleMetering.attributes.Divisor:read(device), METERING_ENDPOINT)
  send_to_endpoint(device, SimpleMetering.attributes.Multiplier:read(device), METERING_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ActivePower:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.RMSVoltage:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.RMSCurrent:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACPowerMultiplier:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACPowerDivisor:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACVoltageMultiplier:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACVoltageDivisor:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACCurrentMultiplier:read(device), ELECTRICAL_ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACCurrentDivisor:read(device), ELECTRICAL_ENDPOINT)

  if TemperatureMeasurement ~= nil and TemperatureMeasurement.attributes ~= nil and TemperatureMeasurement.attributes.MeasuredValue ~= nil then
    send_to_endpoint(device, TemperatureMeasurement.attributes.MeasuredValue:read(device), TEMPERATURE_ENDPOINT)
  end

  for _, pref in pairs(PREFERENCES) do
    read_mfg_attr(device, pref.attr)
  end
end

local function device_added(driver, device)
  log.info(string.format("Added %s (%s)", device.label, device:get_model() or "unknown-model"))
  initialize_scalars(device)
  apply_preference_defaults(device, "added/default sync")
  refresh_device_state(device)
end

local function device_init(driver, device)
  initialize_scalars(device)
  device:set_component_to_endpoint_fn(function(_, component_id)
    return CONTROL_ENDPOINT
  end)
  device:set_endpoint_to_component_fn(function(_, endpoint)
    return "main"
  end)
  for _, attribute in ipairs(CONFIGURED_ATTRIBUTES) do
    device:add_configured_attribute(attribute)
  end
end

local function configure_and_refresh(device, reason)
  local why = reason or "unspecified"
  log.info(string.format("Configuring/refreshing %s (%s)", device.label, why))
  initialize_scalars(device)
  device:configure()
  apply_preference_defaults(device, why .. "/default sync")
  refresh_device_state(device)
end

local function device_do_configure(driver, device)
  configure_and_refresh(device, "doConfigure")
end

local function device_driver_switched(driver, device)
  -- Manual driver changes do not always behave exactly like a fresh join.
  -- Re-run the same safe configure/refresh path so voltage/current reporting and
  -- the outlet profile have a chance to settle without requiring delete/re-add.
  configure_and_refresh(device, "driverSwitched")
end

local function device_info_changed(driver, device, event, args)
  apply_preference_changes(device, args)
end

local function refresh_handler(driver, device, command)
  refresh_device_state(device)
end

local function build_onoff_command(device, is_on)
  -- Official SmartThings Zigbee defaults use OnOff.commands.server.*.
  -- Keep tiny fallbacks for hub/library variants, but prefer the documented path.
  if OnOff.commands ~= nil and OnOff.commands.server ~= nil then
    return is_on and OnOff.commands.server.On(device) or OnOff.commands.server.Off(device)
  end
  if OnOff.server ~= nil and OnOff.server.commands ~= nil then
    return is_on and OnOff.server.commands.On(device) or OnOff.server.commands.Off(device)
  end
  if OnOff.On ~= nil and OnOff.Off ~= nil then
    return is_on and OnOff.On(device) or OnOff.Off(device)
  end
  return nil
end

local function switch_command_handler(is_on)
  return function(driver, device, command)
    local command_name = is_on and "ON" or "OFF"
    local primary_cmd = build_onoff_command(device, is_on)
    if primary_cmd == nil then
      log.error("Unable to construct OnOff command for outlet")
      return
    end

    log.info(string.format("Sending outlet %s command to primary endpoint %d", command_name, CONTROL_ENDPOINT))
    send_to_endpoint(device, primary_cmd, CONTROL_ENDPOINT)

    -- Some reports show endpoint 2 as the actual relay, while endpoint 1 also exposes OnOff.
    -- During no-log external testing, send a fallback command to EP1 as well.
    -- If EP1 is the dummy switch reported by ZHA, this is harmless; if firmware differs, it rescues control.
    local fallback_cmd = build_onoff_command(device, is_on)
    if fallback_cmd ~= nil then
      log.debug(string.format("Sending outlet %s fallback command to endpoint %d", command_name, FALLBACK_CONTROL_ENDPOINT))
      send_to_endpoint(device, fallback_cmd, FALLBACK_CONTROL_ENDPOINT)
    end

    log.debug(string.format("Reading outlet OnOff state from endpoint %d after command", CONTROL_ENDPOINT))
    send_to_endpoint(device, OnOff.attributes.OnOff:read(device), CONTROL_ENDPOINT)
    log.debug(string.format("Reading fallback OnOff state from endpoint %d after command", FALLBACK_CONTROL_ENDPOINT))
    send_to_endpoint(device, OnOff.attributes.OnOff:read(device), FALLBACK_CONTROL_ENDPOINT)
  end
end

local function analog_power_is_fresh(device)
  local last_seen = device:get_field(FIELD_ANALOG_POWER_SEEN_AT)
  return last_seen ~= nil and (os.time() - last_seen) <= ANALOG_POWER_FRESH_SECONDS
end

local function on_off_attr_handler(driver, device, value, zb_rx)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if endpoint ~= CONTROL_ENDPOINT and endpoint ~= FALLBACK_CONTROL_ENDPOINT then
    log.debug(string.format("Ignoring OnOff state from unrelated endpoint %d", endpoint))
    return
  end
  if endpoint == FALLBACK_CONTROL_ENDPOINT then
    log.debug(string.format("Accepting fallback OnOff state from endpoint %d", endpoint))
  end
  device:emit_event(value.value and capabilities.switch.switch.on() or capabilities.switch.switch.off())
end

local function analog_power_attr_handler(driver, device, value, zb_rx)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if endpoint ~= ANALOG_POWER_ENDPOINT then
    return
  end
  local watts = round(tonumber(simple_value(value)) or 0, 1)
  device:set_field(FIELD_ANALOG_POWER_SEEN_AT, os.time())
  device:emit_event(capabilities.powerMeter.power({ value = watts, unit = "W" }))
end

local function active_power_attr_handler(driver, device, value, zb_rx)
  if analog_power_is_fresh(device) then
    return
  end
  local raw = tonumber(simple_value(value)) or 0
  local mult = device:get_field(FIELD_ELEC_POWER_MULT) or 1
  local div = device:get_field(FIELD_ELEC_POWER_DIV) or 10
  if div == 0 then div = 1 end
  device:emit_event(capabilities.powerMeter.power({ value = round((raw * mult) / div, 1), unit = "W" }))
end

local function energy_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value)) or 0
  local mult = device:get_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY) or 1
  local div = device:get_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY) or 1000
  if div == 0 then div = 1 end
  local kwh = round((raw * mult) / div, 3)
  local previous = device:get_field(FIELD_LAST_ENERGY)
  if previous ~= nil and kwh < previous then
    log.debug(string.format("Ignoring lower energy value %.3f kWh because previous value is %.3f kWh", kwh, previous))
    return
  end
  device:set_field(FIELD_LAST_ENERGY, kwh, { persist = true })
  device:emit_event(capabilities.energyMeter.energy({ value = kwh, unit = "kWh" }))
end

local function voltage_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value)) or 0
  local mult = device:get_field(FIELD_ELEC_VOLTAGE_MULT) or 1
  local div = device:get_field(FIELD_ELEC_VOLTAGE_DIV) or 1
  if div == 0 then div = 1 end
  device:emit_event(capabilities.voltageMeasurement.voltage({ value = round((raw * mult) / div, 1), unit = "V" }))
end

local function current_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value)) or 0
  local mult = device:get_field(FIELD_ELEC_CURRENT_MULT) or 1
  local div = device:get_field(FIELD_ELEC_CURRENT_DIV) or 1000
  if div == 0 then div = 1 end
  device:emit_event(capabilities.currentMeasurement.current({ value = round((raw * mult) / div, 3), unit = "A" }))
end

local function temperature_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value))
  if raw == nil or raw ~= raw then return end
  if raw == 0 then
    log.debug("Ignoring zero TemperatureMeasurement value; public ZHA diagnostics report this cluster may stay at 0 without a quirk")
    return
  end

  local last_aggregate_temp_at = device:get_field(FIELD_LAST_AGGREGATE_TEMP_AT) or 0
  if (os.time() - last_aggregate_temp_at) < AGGREGATE_TEMP_PREFER_SECONDS then
    log.debug("Suppressing standard TemperatureMeasurement because a recent Aqara aggregate temperature is preferred")
    return
  end

  local temp_c = round(raw / 100, 1)
  if temp_c < -40 or temp_c > 125 then
    log.debug(string.format("Ignoring implausible standard temperature %.1f C", temp_c))
    return
  end
  device:emit_event(capabilities.temperatureMeasurement.temperature({ value = temp_c, unit = "C" }))
end

local function make_set_field_handler(field, default)
  return function(driver, device, value, zb_rx)
    local raw = tonumber(simple_value(value))
    if raw ~= nil and raw ~= 0 then
      device:set_field(field, raw, { persist = true })
    elseif default ~= nil then
      device:set_field(field, default, { persist = true })
    end
  end
end

local function bytes_from_value(value)
  local raw = simple_value(value)

  if type(raw) == "string" then
    local bytes = {}
    for i = 1, #raw do
      bytes[#bytes + 1] = string.byte(raw, i)
    end
    return bytes
  end

  if type(raw) == "table" then
    local bytes = {}
    for i = 1, #raw do
      if type(raw[i]) == "number" then
        bytes[#bytes + 1] = raw[i]
      elseif type(raw[i]) == "table" and raw[i].value ~= nil then
        bytes[#bytes + 1] = raw[i].value
      end
    end
    if #bytes > 0 then
      return bytes
    end

    -- Some SmartThings data type wrappers keep the byte string one level deeper.
    for _, key in ipairs({ "data", "bytes", "buf", "buffer", "_value" }) do
      if raw[key] ~= nil then
        return bytes_from_value(raw[key])
      end
    end
  end

  return nil
end

local function u16_le(bytes, index)
  return (bytes[index] or 0) + ((bytes[index + 1] or 0) * 256)
end

local function i16_le(bytes, index)
  local value = u16_le(bytes, index)
  if value >= 0x8000 then value = value - 0x10000 end
  return value
end

local function uint_le(bytes, index, size)
  local value = 0
  local factor = 1
  for offset = 0, size - 1 do
    value = value + ((bytes[index + offset] or 0) * factor)
    factor = factor * 256
  end
  return value
end

local function sint_le(bytes, index, size)
  local value = uint_le(bytes, index, size)
  local sign_limit = 2 ^ ((size * 8) - 1)
  local full_range = 2 ^ (size * 8)
  if value >= sign_limit then value = value - full_range end
  return value
end

local function u32_le(bytes, index)
  return uint_le(bytes, index, 4)
end

local function i32_le(bytes, index)
  return sint_le(bytes, index, 4)
end

local function f32_le(bytes, index)
  local word = u32_le(bytes, index)
  local sign = math.floor(word / 0x80000000)
  local exponent = math.floor(word / 0x800000) % 0x100
  local mantissa = word % 0x800000

  if exponent == 0 and mantissa == 0 then
    return sign == 1 and -0.0 or 0.0
  end
  if exponent == 0xFF then
    return nil
  end

  local value
  if exponent == 0 then
    value = (mantissa / 0x800000) * (2 ^ -126)
  else
    value = (1 + (mantissa / 0x800000)) * (2 ^ (exponent - 127))
  end

  if sign == 1 then value = -value end
  return value
end

local function f16_le(bytes, index)
  local word = u16_le(bytes, index)
  local sign = math.floor(word / 0x8000)
  local exponent = math.floor(word / 0x400) % 0x20
  local mantissa = word % 0x400

  if exponent == 0 and mantissa == 0 then
    return sign == 1 and -0.0 or 0.0
  end
  if exponent == 0x1F then
    return nil
  end

  local value
  if exponent == 0 then
    value = (mantissa / 0x400) * (2 ^ -14)
  else
    value = (1 + (mantissa / 0x400)) * (2 ^ (exponent - 15))
  end

  if sign == 1 then value = -value end
  return value
end

local function f64_le(bytes, index)
  local low = u32_le(bytes, index)
  local high = u32_le(bytes, index + 4)
  local sign = math.floor(high / 0x80000000)
  local exponent = math.floor(high / 0x100000) % 0x800
  local mantissa_high = high % 0x100000
  local mantissa = (mantissa_high * (2 ^ 32)) + low

  if exponent == 0 and mantissa == 0 then
    return sign == 1 and -0.0 or 0.0
  end
  if exponent == 0x7FF then
    return nil
  end

  local value
  if exponent == 0 then
    value = (mantissa / (2 ^ 52)) * (2 ^ -1022)
  else
    value = (1 + (mantissa / (2 ^ 52))) * (2 ^ (exponent - 1023))
  end

  if sign == 1 then value = -value end
  return value
end

local function tlv_fixed_size(data_type)
  if data_type == 0x08 or data_type == 0x10 then
    return 1
  elseif data_type >= 0x18 and data_type <= 0x1F then
    return data_type - 0x17
  elseif data_type >= 0x20 and data_type <= 0x27 then
    return data_type - 0x1F
  elseif data_type >= 0x28 and data_type <= 0x2F then
    return data_type - 0x27
  elseif data_type == 0x30 then
    return 1
  elseif data_type == 0x31 then
    return 2
  elseif data_type == 0x38 then
    return 2
  elseif data_type == 0x39 then
    return 4
  elseif data_type == 0x3A then
    return 8
  end
  return nil
end

local function parse_tlv_value(bytes, index, data_type)
  if data_type == 0x08 then
    return bytes[index], 1
  elseif data_type == 0x10 then
    return bytes[index] ~= 0, 1
  elseif data_type >= 0x18 and data_type <= 0x1F then
    local size = data_type - 0x17
    return uint_le(bytes, index, size), size
  elseif data_type >= 0x20 and data_type <= 0x27 then
    local size = data_type - 0x1F
    return uint_le(bytes, index, size), size
  elseif data_type >= 0x28 and data_type <= 0x2F then
    local size = data_type - 0x27
    return sint_le(bytes, index, size), size
  elseif data_type == 0x30 then
    return uint_le(bytes, index, 1), 1
  elseif data_type == 0x31 then
    return uint_le(bytes, index, 2), 2
  elseif data_type == 0x38 then
    return f16_le(bytes, index), 2
  elseif data_type == 0x39 then
    return f32_le(bytes, index), 4
  elseif data_type == 0x3A then
    return f64_le(bytes, index), 8
  end

  return nil, tlv_fixed_size(data_type)
end

local function normalize_voltage(value)
  if value == nil then return nil end
  local n = tonumber(value)
  if n == nil then return nil end
  -- Aqara aggregate examples report voltage as 2470 for 247.0 V.
  if n > 1000 and n < 10000 then
    n = n / 10
  elseif n > 10000 then
    n = n / 1000
  end
  if n < 80 or n > 280 then
    log.debug(string.format("Ignoring implausible aggregate voltage %.3f", n))
    return nil
  end
  return round(n, 1)
end

local function normalize_current(value)
  if value == nil then return nil end
  local n = tonumber(value)
  if n == nil then return nil end
  -- Aqara aggregate examples report current as mA-like values, e.g. 931 -> 0.931 A.
  if n > 32 then
    n = n / 1000
  end
  if n < 0 or n > 32 then
    log.debug(string.format("Ignoring implausible aggregate current %.3f", n))
    return nil
  end
  return round(n, 3)
end

local function normalize_power(value)
  if value == nil then return nil end
  local n = tonumber(value)
  if n == nil then return nil end
  if n < 0 or n > 5000 then
    log.debug(string.format("Ignoring implausible aggregate power %.3f", n))
    return nil
  end
  return round(n, 1)
end

local function choose_aggregate_current(seen)
  local candidates = {}
  for _, tag in ipairs({ 0x97, 0x95 }) do
    if seen[tag] ~= nil then
      local current = normalize_current(seen[tag])
      local raw = tonumber(seen[tag])
      if current ~= nil then
        candidates[#candidates + 1] = { tag = tag, current = current, raw = raw }
      end
    end
  end

  if #candidates == 0 then
    return nil
  end

  local voltage = normalize_voltage(seen[0x96])
  local power = normalize_power(seen[0x98])
  if voltage ~= nil and voltage > 0 and power ~= nil then
    local expected = power / voltage
    table.sort(candidates, function(a, b)
      return math.abs(a.current - expected) < math.abs(b.current - expected)
    end)

    local delta = math.abs(candidates[1].current - expected)
    if delta <= math.max(0.1, expected * 0.5) then
      log.debug(string.format(
        "Using aggregate current tag 0x%02X because %.3f A is closest to P/V estimate %.3f A",
        candidates[1].tag,
        candidates[1].current,
        expected
      ))
      return candidates[1].current
    end
  end

  -- Prefer raw mA-style values (>32) when P/V cannot disambiguate.
  for _, candidate in ipairs(candidates) do
    if candidate.raw ~= nil and candidate.raw > 32 then
      log.debug(string.format("Using aggregate current tag 0x%02X as mA-style value", candidate.tag))
      return candidate.current
    end
  end

  -- Public plug-family examples disagree on 0x95 vs 0x97. If both are low/ambiguous,
  -- prefer 0x95 because the deCONZ Xiaomi aggregate documentation labels it as current.
  for _, candidate in ipairs(candidates) do
    if candidate.tag == 0x95 then
      log.debug("Using aggregate current tag 0x95 as low-value fallback")
      return candidate.current
    end
  end

  log.debug(string.format("Using aggregate current tag 0x%02X as final fallback", candidates[1].tag))
  return candidates[1].current
end

local function aggregate_attr_handler(driver, device, value, zb_rx)
  local attr = zb_rx.body.zcl_body.attr_records[1].attr_id.value
  local bytes = bytes_from_value(value)

  if bytes == nil or #bytes == 0 then
    log.debug(string.format("Received Aqara aggregate attr 0x%04X but could not extract byte payload: %s", attr, tostring(simple_value(value))))
    return
  end

  log.debug(string.format("Parsing Aqara aggregate attr 0x%04X with %d bytes", attr, #bytes))

  local index = 1
  local seen = {}
  while index + 2 <= #bytes do
    local tag = bytes[index]
    local data_type = bytes[index + 1]
    local decoded, size = parse_tlv_value(bytes, index + 2, data_type)

    if size == nil then
      log.debug(string.format(
        "Stopping aggregate parse at byte %d: unsupported variable-size type 0x%02X for tag 0x%02X",
        index,
        data_type or 0,
        tag or 0
      ))
      break
    end

    if index + 1 + size > #bytes then
      log.debug(string.format(
        "Stopping aggregate parse at byte %d: truncated value type 0x%02X for tag 0x%02X needs %d bytes but only %d remain",
        index,
        data_type or 0,
        tag or 0,
        size,
        #bytes - index - 1
      ))
      break
    end

    if decoded == nil then
      log.debug(string.format(
        "Skipping aggregate tag 0x%02X type 0x%02X at byte %d because the fixed-size value could not be decoded",
        tag or 0,
        data_type or 0,
        index
      ))
    else
      log.debug(string.format("Aqara aggregate tag 0x%02X type 0x%02X value %s", tag, data_type, tostring(decoded)))
      seen[tag] = decoded
    end

    index = index + 2 + size
  end

  -- Known Xiaomi/Aqara aggregate tags used by related plugs/modules:
  -- 0x03 device temperature, 0x05 power outage count, 0x96 voltage, 0x98 power.
  -- Current has appeared as either 0x95 or 0x97 in public plug-family examples;
  -- prefer a candidate that looks like mA/A and keep energy/consumption on 0x95/0x97 out
  -- of SmartThings energy because SimpleMetering already works reliably.
  if seen[0x03] ~= nil then
    local temp = tonumber(seen[0x03])
    if temp ~= nil and temp == temp and temp > -40 and temp < 125 then
      device:set_field(FIELD_LAST_AGGREGATE_TEMP_AT, os.time())
      device:emit_event(capabilities.temperatureMeasurement.temperature({ value = round(temp, 1), unit = "C" }))
    else
      log.debug(string.format("Ignoring implausible aggregate device temperature %s", tostring(seen[0x03])))
    end
  end

  if seen[0x96] ~= nil then
    local voltage = normalize_voltage(seen[0x96])
    if voltage ~= nil then
      device:emit_event(capabilities.voltageMeasurement.voltage({ value = voltage, unit = "V" }))
    end
  end

  local current = choose_aggregate_current(seen)
  if current ~= nil then
    device:emit_event(capabilities.currentMeasurement.current({ value = current, unit = "A" }))
  end

  if seen[0x98] ~= nil and not analog_power_is_fresh(device) then
    local power = normalize_power(seen[0x98])
    if power ~= nil then
      device:emit_event(capabilities.powerMeter.power({ value = power, unit = "W" }))
    end
  end

  if seen[0x05] ~= nil then
    log.info(string.format("Aqara aggregate power outage count reported as %s; not emitted because no stock SmartThings capability is used for it", tostring(seen[0x05])))
  end
end

local function mfg_attr_handler(driver, device, value, zb_rx)
  local attr = zb_rx.body.zcl_body.attr_records[1].attr_id.value
  log.debug(string.format("Received Aqara outlet attr 0x%04X: %s", attr, tostring(simple_value(value))))
end

local capability_handlers = {
  [capabilities.refresh.ID] = {
    [capabilities.refresh.commands.refresh.NAME] = refresh_handler,
  },
  [capabilities.switch.ID] = {
    [capabilities.switch.commands.on.NAME] = switch_command_handler(true),
    [capabilities.switch.commands.off.NAME] = switch_command_handler(false),
  },
}

local zigbee_handlers = {
  attr = {
    [OnOff.ID] = {
      [OnOff.attributes.OnOff.ID] = on_off_attr_handler,
    },
    [AnalogInput.ID] = {
      [AnalogInput.attributes.PresentValue.ID] = analog_power_attr_handler,
    },
    [SimpleMetering.ID] = {
      [SimpleMetering.attributes.CurrentSummationDelivered.ID] = energy_attr_handler,
      [SimpleMetering.attributes.Divisor.ID] = make_set_field_handler(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY, 1000),
      [SimpleMetering.attributes.Multiplier.ID] = make_set_field_handler(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY, 1),
    },
    [ElectricalMeasurement.ID] = {
      [ElectricalMeasurement.attributes.ActivePower.ID] = active_power_attr_handler,
      [ElectricalMeasurement.attributes.RMSVoltage.ID] = voltage_attr_handler,
      [ElectricalMeasurement.attributes.RMSCurrent.ID] = current_attr_handler,
      [ElectricalMeasurement.attributes.ACPowerMultiplier.ID] = make_set_field_handler(FIELD_ELEC_POWER_MULT, 1),
      [ElectricalMeasurement.attributes.ACPowerDivisor.ID] = make_set_field_handler(FIELD_ELEC_POWER_DIV, 10),
      [ElectricalMeasurement.attributes.ACVoltageMultiplier.ID] = make_set_field_handler(FIELD_ELEC_VOLTAGE_MULT, 1),
      [ElectricalMeasurement.attributes.ACVoltageDivisor.ID] = make_set_field_handler(FIELD_ELEC_VOLTAGE_DIV, 1),
      [ElectricalMeasurement.attributes.ACCurrentMultiplier.ID] = make_set_field_handler(FIELD_ELEC_CURRENT_MULT, 1),
      [ElectricalMeasurement.attributes.ACCurrentDivisor.ID] = make_set_field_handler(FIELD_ELEC_CURRENT_DIV, 1000),
    },
    [AQARA_CLUSTER_ID] = {
      [ATTR_BUTTON_LOCK] = mfg_attr_handler,
      [ATTR_CHARGING_PROTECTION] = mfg_attr_handler,
      [ATTR_LED_INDICATOR] = mfg_attr_handler,
      [ATTR_CHARGING_LIMIT] = mfg_attr_handler,
      [ATTR_OVERLOAD_PROTECTION] = mfg_attr_handler,
      [ATTR_POWER_ON_BEHAVIOR] = mfg_attr_handler,
      -- Xiaomi/Aqara aggregate attribute containers. Logging these helps a
      -- tester capture device_temperature/power_outage_count style payloads
      -- without risking an incomplete parser in the first external build.
      [0x00F7] = aggregate_attr_handler,
      [0xFF01] = aggregate_attr_handler,
    },
  },
}

if TemperatureMeasurement ~= nil and TemperatureMeasurement.attributes ~= nil and TemperatureMeasurement.attributes.MeasuredValue ~= nil then
  zigbee_handlers.attr[TemperatureMeasurement.ID] = {
    [TemperatureMeasurement.attributes.MeasuredValue.ID] = temperature_attr_handler,
  }
end

local lifecycle_handlers = {
  added = device_added,
  init = device_init,
  doConfigure = device_do_configure,
  driverSwitched = device_driver_switched,
  infoChanged = device_info_changed,
}

return {
  lifecycle_handlers = lifecycle_handlers,
  capability_handlers = capability_handlers,
  zigbee_handlers = zigbee_handlers,
}
