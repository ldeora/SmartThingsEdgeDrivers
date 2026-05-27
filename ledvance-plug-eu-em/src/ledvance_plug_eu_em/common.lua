local capabilities = require "st.capabilities"
local cluster_base = require "st.zigbee.cluster_base"
local clusters = require "st.zigbee.zcl.clusters"
local data_types = require "st.zigbee.data_types"
local zigbee_constants = require "st.zigbee.constants"
local log = require "log"

local OnOff = clusters.OnOff
local SimpleMetering = clusters.SimpleMetering
local ElectricalMeasurement = clusters.ElectricalMeasurement

local ENDPOINT = 1
local STARTUP_ONOFF_ATTR_ID = 0x4003

local FIELD_ELEC_POWER_MULT = "ledvance_plug_eu_em_elec_power_mult"
local FIELD_ELEC_POWER_DIV = "ledvance_plug_eu_em_elec_power_div"
local FIELD_ELEC_VOLTAGE_MULT = "ledvance_plug_eu_em_elec_voltage_mult"
local FIELD_ELEC_VOLTAGE_DIV = "ledvance_plug_eu_em_elec_voltage_div"
local FIELD_ELEC_CURRENT_MULT = "ledvance_plug_eu_em_elec_current_mult"
local FIELD_ELEC_CURRENT_DIV = "ledvance_plug_eu_em_elec_current_div"
local FIELD_STARTUP_ONOFF = "ledvance_plug_eu_em_startup_onoff"

local POWER_ON_BEHAVIOR_VALUES = {
  off = 0x00,
  on = 0x01,
  toggle = 0x02,
  previous = 0xFF,
}

local POWER_ON_BEHAVIOR_NAMES = {
  [0x00] = "off",
  [0x01] = "on",
  [0x02] = "toggle",
  [0xFF] = "previous",
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
    maximum_interval = 600,
    data_type = ElectricalMeasurement.attributes.ActivePower.base_type,
    reportable_change = 1,
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

local function simple_value(value)
  if value == nil then return nil end
  if type(value) == "table" and value.value ~= nil then
    return value.value
  end
  return value
end

local function send_to_endpoint(device, zigbee_message, endpoint)
  if endpoint ~= nil then
    device:send(zigbee_message:to_endpoint(endpoint))
  else
    device:send(zigbee_message)
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
  device:set_field(FIELD_ELEC_POWER_DIV, device:get_field(FIELD_ELEC_POWER_DIV) or 1, { persist = true })
  device:set_field(FIELD_ELEC_VOLTAGE_MULT, device:get_field(FIELD_ELEC_VOLTAGE_MULT) or 1, { persist = true })
  device:set_field(FIELD_ELEC_VOLTAGE_DIV, device:get_field(FIELD_ELEC_VOLTAGE_DIV) or 1, { persist = true })
  device:set_field(FIELD_ELEC_CURRENT_MULT, device:get_field(FIELD_ELEC_CURRENT_MULT) or 1, { persist = true })
  device:set_field(FIELD_ELEC_CURRENT_DIV, device:get_field(FIELD_ELEC_CURRENT_DIV) or 1000, { persist = true })
end

local function get_preference_old_value(args, preference_name)
  if args == nil or args.old_st_store == nil or args.old_st_store.preferences == nil then
    return nil
  end
  return args.old_st_store.preferences[preference_name]
end

local function preference_changed(old_value, new_value)
  if old_value == nil or new_value == nil then
    return false
  end
  return old_value ~= new_value
end

local function effective_preference_value(device, pref_name)
  if device.preferences ~= nil then
    return device.preferences[pref_name]
  end
  return nil
end

local function read_startup_onoff(device)
  local msg = cluster_base.read_attribute(device, data_types.ClusterId(OnOff.ID), STARTUP_ONOFF_ATTR_ID)
  send_to_endpoint(device, msg, ENDPOINT)
end

local function build_startup_onoff_write(device, raw_value)
  local startup_type = data_types.Uint8
  if OnOff.attributes ~= nil and OnOff.attributes.StartUpOnOff ~= nil and OnOff.attributes.StartUpOnOff.base_type ~= nil then
    startup_type = OnOff.attributes.StartUpOnOff.base_type
  end
  if OnOff.attributes ~= nil and OnOff.attributes.StartUpOnOff ~= nil and OnOff.attributes.StartUpOnOff.write ~= nil then
    return OnOff.attributes.StartUpOnOff:write(device, startup_type(raw_value))
  end
  if cluster_base.write_attribute ~= nil then
    return cluster_base.write_attribute(device, data_types.ClusterId(OnOff.ID), STARTUP_ONOFF_ATTR_ID, startup_type, startup_type(raw_value))
  end
  return nil
end

local function write_power_on_behavior(device, behavior, reason)
    if behavior == nil or POWER_ON_BEHAVIOR_VALUES[behavior] == nil then
    log.warn(string.format("Ignoring unsupported powerOnBehavior value: %s", tostring(behavior)))
    return
  end
  local raw = POWER_ON_BEHAVIOR_VALUES[behavior]
  local msg = build_startup_onoff_write(device, raw)
  if msg == nil then
    log.error("Unable to construct StartUpOnOff write message")
    return
  end
  log.info(string.format("Applying powerOnBehavior=%s on %s endpoint %d (%s)", tostring(behavior), device.label, ENDPOINT, reason or "preference update"))
  send_to_endpoint(device, msg, ENDPOINT)
  read_startup_onoff(device)
end

local function apply_preference_changes(device, args)
  local old_value = get_preference_old_value(args, "powerOnBehavior")
  local new_value = effective_preference_value(device, "powerOnBehavior")
  if preference_changed(old_value, new_value) then
    write_power_on_behavior(device, new_value, "preference change")
  else
    log.debug("No powerOnBehavior preference write needed")
  end
end

local function refresh_device_state(device)
  log.debug("Refreshing switch state, startup behavior, metering and electrical values")
  send_to_endpoint(device, OnOff.attributes.OnOff:read(device), ENDPOINT)
  read_startup_onoff(device)
  send_to_endpoint(device, SimpleMetering.attributes.CurrentSummationDelivered:read(device), ENDPOINT)
  send_to_endpoint(device, SimpleMetering.attributes.Divisor:read(device), ENDPOINT)
  send_to_endpoint(device, SimpleMetering.attributes.Multiplier:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ActivePower:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.RMSVoltage:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.RMSCurrent:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACPowerMultiplier:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACPowerDivisor:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACVoltageMultiplier:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACVoltageDivisor:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACCurrentMultiplier:read(device), ENDPOINT)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACCurrentDivisor:read(device), ENDPOINT)
end

local function device_added(driver, device)
  log.info(string.format("Added %s (%s)", device.label, device:get_model() or "unknown-model"))
  initialize_scalars(device)
  refresh_device_state(device)
end

local function device_init(driver, device)
  initialize_scalars(device)
  device:set_component_to_endpoint_fn(function(_, component_id)
    return ENDPOINT
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
  refresh_device_state(device)
end

local function device_do_configure(driver, device)
  configure_and_refresh(device, "doConfigure")
end

local function device_driver_switched(driver, device)
  configure_and_refresh(device, "driverSwitched")
end

local function device_info_changed(driver, device, event, args)
  apply_preference_changes(device, args)
end

local function refresh_handler(driver, device, command)
  refresh_device_state(device)
end

local function build_onoff_command(device, is_on)
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
    local cmd = build_onoff_command(device, is_on)
    if cmd == nil then
      log.error("Unable to construct OnOff command for plug")
      return
    end
    send_to_endpoint(device, cmd, ENDPOINT)
    send_to_endpoint(device, OnOff.attributes.OnOff:read(device), ENDPOINT)
  end
end

local function on_off_attr_handler(driver, device, value, zb_rx)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if endpoint ~= ENDPOINT then
    return
  end
  device:emit_event(value.value and capabilities.switch.switch.on() or capabilities.switch.switch.off())
end

local function energy_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value)) or 0
  local mult = device:get_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY) or 1
  local div = device:get_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY) or 1000
  if div == 0 then div = 1 end
  local kwh = round((raw * mult) / div, 3)
  device:emit_event(capabilities.energyMeter.energy({ value = kwh, unit = "kWh" }))
end

local function power_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value)) or 0
  local mult = device:get_field(FIELD_ELEC_POWER_MULT) or 1
  local div = device:get_field(FIELD_ELEC_POWER_DIV) or 1
  if div == 0 then div = 1 end
  device:emit_event(capabilities.powerMeter.power({ value = round((raw * mult) / div, 1), unit = "W" }))
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

local function startup_onoff_attr_handler(driver, device, value, zb_rx)
  local raw = tonumber(simple_value(value))
  if raw == nil then return end
  device:set_field(FIELD_STARTUP_ONOFF, raw, { persist = true })
  local decoded = POWER_ON_BEHAVIOR_NAMES[raw] or string.format("0x%02X", raw)
  log.info(string.format("Device reports powerOnBehavior=%s (%s)", decoded, tostring(raw)))
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
      [STARTUP_ONOFF_ATTR_ID] = startup_onoff_attr_handler,
    },
    [SimpleMetering.ID] = {
      [SimpleMetering.attributes.CurrentSummationDelivered.ID] = energy_attr_handler,
      [SimpleMetering.attributes.Divisor.ID] = make_set_field_handler(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY, 1000),
      [SimpleMetering.attributes.Multiplier.ID] = make_set_field_handler(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY, 1),
    },
    [ElectricalMeasurement.ID] = {
      [ElectricalMeasurement.attributes.ActivePower.ID] = power_attr_handler,
      [ElectricalMeasurement.attributes.RMSVoltage.ID] = voltage_attr_handler,
      [ElectricalMeasurement.attributes.RMSCurrent.ID] = current_attr_handler,
      [ElectricalMeasurement.attributes.ACPowerMultiplier.ID] = make_set_field_handler(FIELD_ELEC_POWER_MULT, 1),
      [ElectricalMeasurement.attributes.ACPowerDivisor.ID] = make_set_field_handler(FIELD_ELEC_POWER_DIV, 1),
      [ElectricalMeasurement.attributes.ACVoltageMultiplier.ID] = make_set_field_handler(FIELD_ELEC_VOLTAGE_MULT, 1),
      [ElectricalMeasurement.attributes.ACVoltageDivisor.ID] = make_set_field_handler(FIELD_ELEC_VOLTAGE_DIV, 1),
      [ElectricalMeasurement.attributes.ACCurrentMultiplier.ID] = make_set_field_handler(FIELD_ELEC_CURRENT_MULT, 1),
      [ElectricalMeasurement.attributes.ACCurrentDivisor.ID] = make_set_field_handler(FIELD_ELEC_CURRENT_DIV, 1000),
    },
  },
}

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
