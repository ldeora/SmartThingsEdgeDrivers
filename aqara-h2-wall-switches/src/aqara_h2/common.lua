local st_device = require "st.device"
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

local MFG_CODE = 0x115F
local AQARA_CLUSTER_ID = 0xFCC0

local MULTISTATE_INPUT_CLUSTER_ID = 0x0012
local MULTISTATE_PRESENT_VALUE_ATTR_ID = 0x0055

local ATTR_OPERATION_MODE = 0x0200
local ATTR_LED_INDICATOR = 0x0203
local ATTR_FLIP_LED = 0x00F0
local ATTR_LOCK_RELAY = 0x0285
local ATTR_MULTI_CLICK = 0x0286
local ATTR_POWER_ON_MODE = 0x0517

local FIELD_ANALOG_POWER_SEEN_AT = "aqara_h2_analog_power_seen_at"
local FIELD_ELEC_MULT = "aqara_h2_elec_mult"
local FIELD_ELEC_DIV = "aqara_h2_elec_div"
local FIELD_LAST_MFG_PREFIX = "aqara_h2_mfg_"
local FIELD_CHILDREN_EXPECTED = "aqara_h2_children_expected"
local ANALOG_POWER_FRESH_SECONDS = 120

local OP_MODE_VALUES = {
  decoupled = 0x00,
  relay = 0x01,
}

local POWER_ON_MODE_VALUES = {
  on = 0x00,
  previous = 0x01,
  off = 0x02,
  inverted = 0x03,
}

local MODEL_CONFIGS = {
  ["lumi.switch.agl009"] = {
    main_endpoint = 1,
    energy_endpoint = 1,
    power_endpoint = 21,
    switch_endpoints = { 1 },
    button_endpoint_to_component = {
      [1] = "up",
      [4] = "down",
    },
    component_to_endpoint = {
      main = 1,
      up = 1,
      down = 4,
    },
    endpoint_to_component = {
      [1] = "up",
      [4] = "down",
      [21] = "main",
    },
    button_components = { "main", "up", "down" },
    button_supported_values = {
      main = { "pushed", "double", "held" },
      up = { "pushed" },
      down = { "pushed", "double", "held" },
    },
    main_button_count = 2,
    child_relays = {
      { endpoint = 1, key = "relay1", label_suffix = "Relay", profile = "aqara-h2-relay-child" },
    },
    preferences = {
      ledIndicator = { endpoint = 1, attr = ATTR_LED_INDICATOR, kind = "bool" },
      flipLed = { endpoint = 1, attr = ATTR_FLIP_LED, kind = "uint8_bool" },
      powerOnMode = { endpoint = 1, attr = ATTR_POWER_ON_MODE, kind = "power_on_mode" },
      opModeUp = { endpoint = 1, attr = ATTR_OPERATION_MODE, kind = "operation_mode" },
      lockRelayUp = { endpoint = 1, attr = ATTR_LOCK_RELAY, kind = "uint8_bool" },
      multiClickDown = { endpoint = 4, attr = ATTR_MULTI_CLICK, kind = "multi_click" },
    },
  },
  ["lumi.switch.agl010"] = {
    main_endpoint = 1,
    energy_endpoint = 1,
    power_endpoint = 21,
    switch_endpoints = { 1, 2 },
    button_endpoint_to_component = {
      [1] = "left",
      [2] = "right",
      [4] = "leftDown",
      [5] = "rightDown",
    },
    component_to_endpoint = {
      main = 1,
      left = 1,
      right = 2,
      leftDown = 4,
      rightDown = 5,
    },
    endpoint_to_component = {
      [1] = "left",
      [2] = "right",
      [4] = "leftDown",
      [5] = "rightDown",
      [21] = "main",
    },
    button_components = { "main", "left", "right", "leftDown", "rightDown" },
    button_supported_values = {
      main = { "pushed", "double", "held" },
      left = { "pushed" },
      right = { "pushed" },
      leftDown = { "pushed", "double", "held" },
      rightDown = { "pushed", "double", "held" },
    },
    main_button_count = 4,
    child_relays = {
      { endpoint = 1, key = "relay1", label_suffix = "Left Relay", profile = "aqara-h2-relay-child" },
      { endpoint = 2, key = "relay2", label_suffix = "Right Relay", profile = "aqara-h2-relay-child" },
    },
    preferences = {
      ledIndicator = { endpoint = 1, attr = ATTR_LED_INDICATOR, kind = "bool" },
      flipLed = { endpoint = 1, attr = ATTR_FLIP_LED, kind = "uint8_bool" },
      powerOnMode = { endpoint = 1, attr = ATTR_POWER_ON_MODE, kind = "power_on_mode" },
      opModeLeft = { endpoint = 1, attr = ATTR_OPERATION_MODE, kind = "operation_mode" },
      opModeRight = { endpoint = 2, attr = ATTR_OPERATION_MODE, kind = "operation_mode" },
      lockRelayLeft = { endpoint = 1, attr = ATTR_LOCK_RELAY, kind = "uint8_bool" },
      lockRelayRight = { endpoint = 2, attr = ATTR_LOCK_RELAY, kind = "uint8_bool" },
      multiClickLeftDn = { endpoint = 4, attr = ATTR_MULTI_CLICK, kind = "multi_click" },
      multiClickRightDn = { endpoint = 5, attr = ATTR_MULTI_CLICK, kind = "multi_click" },
    },
  },
  ["lumi.switch.agl004"] = {
    main_endpoint = 1,
    energy_endpoint = 1,
    power_endpoint = 21,
    switch_endpoints = { 1 },
    button_endpoint_to_component = {
      [1] = "top",
      [4] = "bottom",
    },
    component_to_endpoint = {
      main = 1,
      top = 1,
      bottom = 4,
    },
    endpoint_to_component = {
      [1] = "top",
      [4] = "bottom",
      [21] = "main",
    },
    button_components = { "main", "top", "bottom" },
    button_supported_values = {
      main = { "pushed", "double", "held" },
      top = { "pushed", "double", "held" },
      bottom = { "pushed", "double", "held" },
    },
    main_button_count = 2,
    child_relays = {
      { endpoint = 1, key = "relay1", label_suffix = "Relay", profile = "aqara-h2-relay-child" },
    },
    preferences = {
      ledIndicator = { endpoint = 1, attr = ATTR_LED_INDICATOR, kind = "bool" },
      flipLed = { endpoint = 1, attr = ATTR_FLIP_LED, kind = "uint8_bool" },
      powerOnMode = { endpoint = 1, attr = ATTR_POWER_ON_MODE, kind = "power_on_mode" },
      opModeTop = { endpoint = 1, attr = ATTR_OPERATION_MODE, kind = "operation_mode" },
      lockRelayTop = { endpoint = 1, attr = ATTR_LOCK_RELAY, kind = "uint8_bool" },
      multiClickBottom = { endpoint = 4, attr = ATTR_MULTI_CLICK, kind = "multi_click" },
    },
  },
  ["lumi.switch.agl005"] = {
    main_endpoint = 1,
    energy_endpoint = 1,
    power_endpoint = 21,
    switch_endpoints = { 1, 2 },
    button_endpoint_to_component = {
      [1] = "top",
      [2] = "bottom",
    },
    component_to_endpoint = {
      main = 1,
      top = 1,
      bottom = 2,
    },
    endpoint_to_component = {
      [1] = "top",
      [2] = "bottom",
      [21] = "main",
    },
    button_components = { "main", "top", "bottom" },
    button_supported_values = {
      main = { "pushed", "double", "held" },
      top = { "pushed", "double", "held" },
      bottom = { "pushed", "double", "held" },
    },
    main_button_count = 2,
    child_relays = {
      { endpoint = 1, key = "relay1", label_suffix = "Top Relay", profile = "aqara-h2-relay-child" },
      { endpoint = 2, key = "relay2", label_suffix = "Bottom Relay", profile = "aqara-h2-relay-child" },
    },
    preferences = {
      ledIndicator = { endpoint = 1, attr = ATTR_LED_INDICATOR, kind = "bool" },
      flipLed = { endpoint = 1, attr = ATTR_FLIP_LED, kind = "uint8_bool" },
      powerOnMode = { endpoint = 1, attr = ATTR_POWER_ON_MODE, kind = "power_on_mode" },
      opModeTop = { endpoint = 1, attr = ATTR_OPERATION_MODE, kind = "operation_mode" },
      opModeBottom = { endpoint = 2, attr = ATTR_OPERATION_MODE, kind = "operation_mode" },
      lockRelayTop = { endpoint = 1, attr = ATTR_LOCK_RELAY, kind = "uint8_bool" },
      lockRelayBottom = { endpoint = 2, attr = ATTR_LOCK_RELAY, kind = "uint8_bool" },
    },
  },
}

local BUTTON_EVENTS = {
  [0] = capabilities.button.button.held,
  [1] = capabilities.button.button.pushed,
  [2] = capabilities.button.button.double,
}

local CONFIGURED_ATTRIBUTES = {
  {
    cluster = OnOff.ID,
    attribute = OnOff.attributes.OnOff.ID,
    minimum_interval = 0,
    maximum_interval = 3600,
    data_type = OnOff.attributes.OnOff.base_type,
  },
  {
    cluster = AnalogInput.ID,
    attribute = AnalogInput.attributes.PresentValue.ID,
    minimum_interval = 0,
    maximum_interval = 600,
    data_type = AnalogInput.attributes.PresentValue.base_type,
    -- PresentValue is SinglePrecisionFloat; non-discrete attributes require a reportable_change.
    -- SinglePrecisionFloat(0,0,0) is the SmartThings community-proven encoding for 1.0.
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
}

local function round(value, places)
  local power = 10 ^ (places or 0)
  return math.floor((value * power) + 0.5) / power
end

local function get_model_config(device)
  return MODEL_CONFIGS[device:get_model()]
end

local function is_parent(device)
  return device.network_type == st_device.NETWORK_TYPE_ZIGBEE
end

local function get_parent_or_self(device)
  if is_parent(device) then
    return device
  end
  return device:get_parent_device()
end

local function get_preference_old_value(args, preference_name)
  if args == nil or args.old_st_store == nil or args.old_st_store.preferences == nil then
    return nil
  end
  return args.old_st_store.preferences[preference_name]
end

local function get_component(device, component_id)
  local profile = device.profile
  local components = profile and profile.components or nil
  if components == nil then
    return nil
  end

  if components[component_id] ~= nil then
    return components[component_id]
  end

  for _, component in pairs(components) do
    if component.id == component_id then
      return component
    end
  end
  return nil
end

local function set_endpoint_mappings(device)
  local config = get_model_config(device)
  if config == nil or not is_parent(device) then
    return
  end

  device:set_component_to_endpoint_fn(function(_, component_id)
    return config.component_to_endpoint[component_id] or config.main_endpoint
  end)

  device:set_endpoint_to_component_fn(function(_, endpoint)
    return config.endpoint_to_component[endpoint] or "main"
  end)
end

local function emit_component_event_by_id(device, component_id, event)
  local component = get_component(device, component_id)
  if component ~= nil then
    device:emit_component_event(component, event)
  else
    log.warn(string.format("No component '%s' found on %s", tostring(component_id), device.label))
  end
end

local function emit_event_if_latest_state_missing(device, component_id, capability, attribute_name, event)
  if device:get_latest_state(component_id, capability.ID, attribute_name) == nil then
    emit_component_event_by_id(device, component_id, event)
  end
end

local function init_button_metadata(device)
  local config = get_model_config(device)
  if config == nil or not is_parent(device) then
    return
  end

  for _, component_id in ipairs(config.button_components) do
    local number = component_id == "main" and config.main_button_count or 1
    local supported = (config.button_supported_values and config.button_supported_values[component_id]) or { "pushed" }
    emit_component_event_by_id(device, component_id,
      capabilities.button.supportedButtonValues(supported, { visibility = { displayed = false } }))
    emit_component_event_by_id(device, component_id,
      capabilities.button.numberOfButtons({ value = number }, { visibility = { displayed = false } }))
    emit_event_if_latest_state_missing(
      device,
      component_id,
      capabilities.button,
      capabilities.button.button.NAME,
      capabilities.button.button.pushed({ state_change = false })
    )
  end
end

local function send_to_endpoint(device, zigbee_message, endpoint)
  if endpoint ~= nil then
    device:send(zigbee_message:to_endpoint(endpoint))
  else
    device:send(zigbee_message)
  end
end

local function build_pref_value(kind, raw_value)
  if kind == "bool" then
    return data_types.Boolean, data_types.Boolean(raw_value == true)
  elseif kind == "uint8_bool" then
    return data_types.Uint8, data_types.Uint8(raw_value and 1 or 0)
  elseif kind == "operation_mode" then
    return data_types.Uint8, data_types.Uint8(OP_MODE_VALUES[raw_value] or OP_MODE_VALUES.relay)
  elseif kind == "power_on_mode" then
    return data_types.Uint8, data_types.Uint8(POWER_ON_MODE_VALUES[raw_value] or POWER_ON_MODE_VALUES.previous)
  elseif kind == "multi_click" then
    return data_types.Uint8, data_types.Uint8(raw_value and 2 or 1)
  end
  return nil, nil
end

local function write_mfg_attr(device, endpoint, attr_id, data_type, value)
  local msg = cluster_base.write_manufacturer_specific_attribute(
    device,
    AQARA_CLUSTER_ID,
    attr_id,
    MFG_CODE,
    data_type,
    value
  )
  send_to_endpoint(device, msg, endpoint)
end

local function read_mfg_attr(device, endpoint, attr_id)
  local msg = cluster_base.read_manufacturer_specific_attribute(
    device,
    AQARA_CLUSTER_ID,
    attr_id,
    MFG_CODE
  )
  send_to_endpoint(device, msg, endpoint)
end

local function relay_for_endpoint(parent, endpoint)
  local config = get_model_config(parent)
  if config == nil then return nil end
  for _, relay in ipairs(config.child_relays) do
    if relay.endpoint == endpoint then
      return relay
    end
  end
  return nil
end

local function child_for_relay(parent, relay)
  if relay == nil then return nil end
  return parent:get_child_by_parent_assigned_key(relay.key)
end

local function endpoint_for_child(child)
  local parent = get_parent_or_self(child)
  local config = get_model_config(parent)
  if config == nil then return nil end
  for _, relay in ipairs(config.child_relays) do
    local candidate = parent:get_child_by_parent_assigned_key(relay.key)
    if candidate ~= nil and candidate.id == child.id then
      return relay.endpoint
    end
  end
  return nil
end

local function simple_value(value)
  if value == nil then return nil end
  if type(value) == "table" and value.value ~= nil then
    return value.value
  end
  return value
end

local function sorted_numeric_keys(map)
  local keys = {}
  for key, _ in pairs(map) do
    table.insert(keys, key)
  end
  table.sort(keys)
  return keys
end

local function refresh_device_state(device)
  local config = get_model_config(device)
  if config == nil then
    return
  end

  for _, endpoint in ipairs(config.switch_endpoints) do
    send_to_endpoint(device, OnOff.attributes.OnOff:read(device), endpoint)
  end

  local multistate_read = cluster_base.read_attribute(device, data_types.ClusterId(MULTISTATE_INPUT_CLUSTER_ID), MULTISTATE_PRESENT_VALUE_ATTR_ID)
  for _, endpoint in ipairs(sorted_numeric_keys(config.button_endpoint_to_component)) do
    send_to_endpoint(device, multistate_read, endpoint)
  end

  send_to_endpoint(device, AnalogInput.attributes.PresentValue:read(device), config.power_endpoint)
  send_to_endpoint(device, SimpleMetering.attributes.CurrentSummationDelivered:read(device), config.energy_endpoint)
  send_to_endpoint(device, SimpleMetering.attributes.Divisor:read(device), config.energy_endpoint)
  send_to_endpoint(device, SimpleMetering.attributes.Multiplier:read(device), config.energy_endpoint)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ActivePower:read(device), config.energy_endpoint)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACPowerMultiplier:read(device), config.energy_endpoint)
  send_to_endpoint(device, ElectricalMeasurement.attributes.ACPowerDivisor:read(device), config.energy_endpoint)

  for _, pref in pairs(config.preferences) do
    read_mfg_attr(device, pref.endpoint, pref.attr)
  end
end

local function preference_changed(old_value, new_value)
  if old_value == nil then
    return true
  end
  return old_value ~= new_value
end

local function apply_preference_changes(device, args)
  local config = get_model_config(device)
  if config == nil then
    return
  end

  for pref_name, pref in pairs(config.preferences) do
    local old_value = get_preference_old_value(args, pref_name)
    local new_value = device.preferences[pref_name]

    if preference_changed(old_value, new_value) then
      local data_type, value = build_pref_value(pref.kind, new_value)
      if value ~= nil and data_type ~= nil then
        log.info(string.format("Applying preference %s=%s on %s endpoint %d attr 0x%04X", pref_name, tostring(new_value), device.label, pref.endpoint, pref.attr))
        write_mfg_attr(device, pref.endpoint, pref.attr, data_type, value)
        read_mfg_attr(device, pref.endpoint, pref.attr)
      else
        log.warn(string.format("No preference encoding found for %s", pref_name))
      end
    end
  end
end

local function ensure_children(driver, device)
  local config = get_model_config(device)
  if config == nil or not is_parent(device) then
    return
  end

  local expected = 0
  for _, relay in ipairs(config.child_relays) do
    expected = expected + 1
    local label = string.format("%s %s", device.label, relay.label_suffix)
    local child = device:get_child_by_parent_assigned_key(relay.key)
    if child == nil then
      log.info(string.format("Creating child %s (%s) for endpoint %d", label, relay.key, relay.endpoint))
      driver:try_create_device({
        type = "EDGE_CHILD",
        label = label,
        profile = relay.profile,
        parent_device_id = device.id,
        parent_assigned_child_key = relay.key,
        vendor_provided_label = label,
      })
    else
      child:try_update_metadata({ profile = relay.profile, vendor_provided_label = label })
    end
  end

  device:set_field(FIELD_CHILDREN_EXPECTED, expected, { persist = true })
end

local function initialize_metering_scalars(device)
  if device:get_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY) == nil then
    device:set_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY, 1000, { persist = true })
  end
  if device:get_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY) == nil then
    device:set_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY, 1, { persist = true })
  end
  if device:get_field(FIELD_ELEC_DIV) == nil then
    device:set_field(FIELD_ELEC_DIV, 10, { persist = true })
  end
  if device:get_field(FIELD_ELEC_MULT) == nil then
    device:set_field(FIELD_ELEC_MULT, 1, { persist = true })
  end
end

local function device_added(driver, device)
  if not is_parent(device) then
    return
  end

  log.info(string.format("Added %s (%s)", device.label, device:get_model() or "unknown-model"))
  set_endpoint_mappings(device)
  ensure_children(driver, device)
  init_button_metadata(device)
  refresh_device_state(device)
end

local function device_init(driver, device)
  if is_parent(device) then
    log.info(string.format("Init parent %s", device.label))
    set_endpoint_mappings(device)
    ensure_children(driver, device)
    init_button_metadata(device)
    initialize_metering_scalars(device)
    for _, attribute in ipairs(CONFIGURED_ATTRIBUTES) do
      device:add_configured_attribute(attribute)
    end
  else
    log.info(string.format("Init child %s", device.label))
  end
end

local function device_do_configure(driver, device)
  if not is_parent(device) then
    return
  end

  log.info(string.format("Configuring %s", device.label))
  set_endpoint_mappings(device)
  device:configure()
  refresh_device_state(device)
end

local function device_info_changed(driver, device, event, args)
  if not is_parent(device) then
    return
  end
  apply_preference_changes(device, args)
end

local function refresh_handler(driver, device, command)
  local parent = get_parent_or_self(device)
  if is_parent(device) then
    refresh_device_state(parent)
  else
    local endpoint = endpoint_for_child(device)
    if endpoint ~= nil then
      send_to_endpoint(parent, OnOff.attributes.OnOff:read(parent), endpoint)
    else
      log.warn(string.format("Unable to resolve endpoint for child %s during refresh; refreshing parent", device.label))
      refresh_device_state(parent)
    end
  end
end

local function make_mfg_attr_cache_handler(attr_id)
  return function(driver, device, value, zb_rx)
    local endpoint = zb_rx.address_header.src_endpoint.value
    local field = string.format("%s%04X_ep%02X", FIELD_LAST_MFG_PREFIX, attr_id, endpoint)
    local cached = simple_value(value)
    if type(cached) == "table" then
      log.warn(string.format("Skipping non-simple cache value for attr 0x%04X endpoint %d", attr_id, endpoint))
      return
    end
    device:set_field(field, cached, { persist = true })
  end
end

local function analog_power_attr_handler(driver, device, value, zb_rx)
  local endpoint = zb_rx.address_header.src_endpoint.value
  local config = get_model_config(device)
  if config == nil or endpoint ~= config.power_endpoint then
    return
  end

  local watts = tonumber(simple_value(value)) or 0
  watts = round(watts, 1)
  device:set_field(FIELD_ANALOG_POWER_SEEN_AT, os.time(), { persist = true })
  device:emit_event(capabilities.powerMeter.power({ value = watts, unit = "W" }))
end

local function analog_power_is_fresh(device)
  local last_seen = device:get_field(FIELD_ANALOG_POWER_SEEN_AT)
  return last_seen ~= nil and (os.time() - last_seen) <= ANALOG_POWER_FRESH_SECONDS
end

local function active_power_attr_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if config == nil or endpoint ~= config.energy_endpoint or analog_power_is_fresh(device) then
    return
  end

  local multiplier = device:get_field(FIELD_ELEC_MULT) or 1
  local divisor = device:get_field(FIELD_ELEC_DIV) or 10
  if divisor == 0 then
    divisor = 1
  end

  local raw = tonumber(simple_value(value)) or 0
  local watts = round((raw * multiplier) / divisor, 1)
  device:emit_event(capabilities.powerMeter.power({ value = watts, unit = "W" }))
end

local function metering_divisor_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if config == nil or endpoint ~= config.energy_endpoint then
    return
  end

  local divisor = tonumber(simple_value(value))
  if divisor ~= nil and divisor ~= 0 then
    device:set_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY, divisor, { persist = true })
  end
end

local function metering_multiplier_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if config == nil or endpoint ~= config.energy_endpoint then
    return
  end

  local multiplier = tonumber(simple_value(value))
  if multiplier ~= nil then
    device:set_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY, multiplier, { persist = true })
  end
end

local function active_power_divisor_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if config == nil or endpoint ~= config.energy_endpoint then
    return
  end

  local divisor = tonumber(simple_value(value))
  if divisor ~= nil and divisor ~= 0 then
    device:set_field(FIELD_ELEC_DIV, divisor, { persist = true })
  end
end

local function active_power_multiplier_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if config == nil or endpoint ~= config.energy_endpoint then
    return
  end

  local multiplier = tonumber(simple_value(value))
  if multiplier ~= nil then
    device:set_field(FIELD_ELEC_MULT, multiplier, { persist = true })
  end
end

local function energy_attr_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  local endpoint = zb_rx.address_header.src_endpoint.value
  if config == nil or endpoint ~= config.energy_endpoint then
    return
  end

  local multiplier = device:get_field(zigbee_constants.SIMPLE_METERING_MULTIPLIER_KEY) or 1
  local divisor = device:get_field(zigbee_constants.SIMPLE_METERING_DIVISOR_KEY) or 1000
  if divisor == 0 then
    divisor = 1
  end

  local raw = tonumber(simple_value(value)) or 0
  local kwh = round((raw * multiplier) / divisor, 3)
  device:emit_event(capabilities.energyMeter.energy({ value = kwh, unit = "kWh" }))
end

local function button_attr_handler(driver, device, value, zb_rx)
  local config = get_model_config(device)
  if config == nil then
    return
  end

  local endpoint = zb_rx.address_header.src_endpoint.value
  local component_id = config.button_endpoint_to_component[endpoint]
  if component_id == nil then
    return
  end

  local raw = tonumber(simple_value(value))
  local event_factory = raw and BUTTON_EVENTS[raw] or nil
  if event_factory == nil then
    log.debug(string.format("Ignoring unsupported button value %s from endpoint %d", tostring(raw), endpoint))
    return
  end

  local event = event_factory({ state_change = true })
  emit_component_event_by_id(device, component_id, event)
  emit_component_event_by_id(device, "main", event)
end

local function on_off_attr_handler(driver, device, value, zb_rx)
  local endpoint = zb_rx.address_header.src_endpoint.value
  local relay = relay_for_endpoint(device, endpoint)
  if relay == nil then
    return
  end

  local child = child_for_relay(device, relay)
  local event = value.value and capabilities.switch.switch.on() or capabilities.switch.switch.off()
  if child ~= nil then
    child:emit_event(event)
  else
    log.warn(string.format("Received switch state for endpoint %d but no child exists yet", endpoint))
  end
end

local function switch_command_handler(is_on)
  return function(driver, device, command)
    local parent = get_parent_or_self(device)
    local endpoint

    if is_parent(device) then
      endpoint = parent:component_to_endpoint(command.component)
    else
      endpoint = endpoint_for_child(device)
    end

    if endpoint == nil then
      log.error(string.format("Unable to resolve endpoint for switch command on %s", device.label))
      return
    end

    local cmd = is_on and OnOff.server.commands.On(parent) or OnOff.server.commands.Off(parent)
    send_to_endpoint(parent, cmd, endpoint)
    send_to_endpoint(parent, OnOff.attributes.OnOff:read(parent), endpoint)
  end
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
    [MULTISTATE_INPUT_CLUSTER_ID] = {
      [MULTISTATE_PRESENT_VALUE_ATTR_ID] = button_attr_handler,
    },
    [AnalogInput.ID] = {
      [AnalogInput.attributes.PresentValue.ID] = analog_power_attr_handler,
    },
    [SimpleMetering.ID] = {
      [SimpleMetering.attributes.CurrentSummationDelivered.ID] = energy_attr_handler,
      [SimpleMetering.attributes.Divisor.ID] = metering_divisor_handler,
      [SimpleMetering.attributes.Multiplier.ID] = metering_multiplier_handler,
    },
    [ElectricalMeasurement.ID] = {
      [ElectricalMeasurement.attributes.ActivePower.ID] = active_power_attr_handler,
      [ElectricalMeasurement.attributes.ACPowerDivisor.ID] = active_power_divisor_handler,
      [ElectricalMeasurement.attributes.ACPowerMultiplier.ID] = active_power_multiplier_handler,
    },
    [AQARA_CLUSTER_ID] = {
      [ATTR_OPERATION_MODE] = make_mfg_attr_cache_handler(ATTR_OPERATION_MODE),
      [ATTR_LED_INDICATOR] = make_mfg_attr_cache_handler(ATTR_LED_INDICATOR),
      [ATTR_FLIP_LED] = make_mfg_attr_cache_handler(ATTR_FLIP_LED),
      [ATTR_LOCK_RELAY] = make_mfg_attr_cache_handler(ATTR_LOCK_RELAY),
      [ATTR_MULTI_CLICK] = make_mfg_attr_cache_handler(ATTR_MULTI_CLICK),
      [ATTR_POWER_ON_MODE] = make_mfg_attr_cache_handler(ATTR_POWER_ON_MODE),
    },
  },
}

local lifecycle_handlers = {
  added = device_added,
  init = device_init,
  doConfigure = device_do_configure,
  infoChanged = device_info_changed,
}

return {
  lifecycle_handlers = lifecycle_handlers,
  capability_handlers = capability_handlers,
  zigbee_handlers = zigbee_handlers,
}
