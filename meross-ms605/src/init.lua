-- Copyright 2026 Andreas Roedl
-- Licensed under the Apache License, Version 2.0

local capabilities = require "st.capabilities"
local clusters = require "st.matter.clusters"
local MatterDriver = require "st.matter.driver"

local DRIVER_NAME = "meross-ms605-presence-sensor"
local DRIVER_VERSION = "0.1.0-alpha4"
local PROFILE_NAME = "meross-ms605"

-- MS605 endpoint model:
--   EP0: Root Node
--   EP1: Illuminance Measurement + Power Source
--   EP2: Occupancy Sensor, Zone 1
--   EP3: Occupancy Sensor, Zone 2
--   EP4: Occupancy Sensor, Zone 3
local ZONE_ENDPOINTS = { 2, 3, 4 }

-- General endpoint-to-component routing. EP1 is explicitly mapped to main for
-- illuminance. Unknown endpoints also fall back to main, matching the normal
-- SmartThings endpoint mapper behavior.
local ENDPOINT_TO_COMPONENT = {
  [1] = "main",
  [2] = "zone1",
  [3] = "zone2",
  [4] = "zone3",
}

-- Only these endpoints are valid sources of Occupancy reports. Keep this
-- separate from ENDPOINT_TO_COMPONENT so an unexpected Occupancy report from
-- EP1 cannot be accepted merely because EP1 maps to main.
local ZONE_COMPONENT_BY_ENDPOINT = {
  [2] = "zone1",
  [3] = "zone2",
  [4] = "zone3",
}

local ZONE_STATE_FIELD_PREFIX = "__ms605_zone_"
local ZONE_HAS_REPORTED_FIELD_PREFIX = "__ms605_zone_has_reported_"
local ZONE_SYNTHETIC_STATE_FIELD_PREFIX = "__ms605_zone_synthetic_state_"
local AGGREGATE_STATE_FIELD = "__ms605_aggregate_presence"
local SYNTHETIC_INIT_TIMER_FIELD = "__ms605_synthetic_init_timer"
local SYNTHETIC_INIT_DELAY_SECONDS = 5

local function zone_state_field(endpoint_id)
  return string.format("%s%d", ZONE_STATE_FIELD_PREFIX, endpoint_id)
end

local function zone_has_reported_field(endpoint_id)
  return string.format("%s%d", ZONE_HAS_REPORTED_FIELD_PREFIX, endpoint_id)
end

local function zone_synthetic_state_field(endpoint_id)
  return string.format("%s%d", ZONE_SYNTHETIC_STATE_FIELD_PREFIX, endpoint_id)
end

local function endpoint_to_component(device, endpoint_id)
  return ENDPOINT_TO_COMPONENT[endpoint_id] or "main"
end

local function install_endpoint_mapping(device)
  device:set_endpoint_to_component_fn(endpoint_to_component)
end

local function get_latest_presence_state(device, component_id)
  return device:get_latest_state(
    component_id,
    capabilities.presenceSensor.ID,
    capabilities.presenceSensor.presence.NAME
  )
end

local function presence_value_to_boolean(value)
  if value == "present" then
    return true
  elseif value == "not present" then
    return false
  end
  return nil
end

local function clear_runtime_presence_state(device)
  -- Current presence states are deliberately not persistent because they can
  -- change frequently. Small persistent markers record only whether a zone has
  -- ever supplied a genuine Matter report and whether its visible default was
  -- synthesized by this driver.
  for _, endpoint_id in ipairs(ZONE_ENDPOINTS) do
    device:set_field(zone_state_field(endpoint_id), nil)
  end
  device:set_field(AGGREGATE_STATE_FIELD, nil)
end

local function restore_runtime_presence_state(device)
  clear_runtime_presence_state(device)

  for _, endpoint_id in ipairs(ZONE_ENDPOINTS) do
    local component_id = ZONE_COMPONENT_BY_ENDPOINT[endpoint_id]
    local latest_value = get_latest_presence_state(device, component_id)
    local latest_boolean = presence_value_to_boolean(latest_value)
    local has_reported = device:get_field(zone_has_reported_field(endpoint_id)) == true
    local synthetic_state = device:get_field(zone_synthetic_state_field(endpoint_id)) == true

    -- Migration from alpha3: that version never synthesized zone states. If a
    -- zone already has a valid stored state and no alpha4 synthetic marker, it
    -- can safely be treated as a genuine previous report.
    if not has_reported and not synthetic_state and latest_boolean ~= nil then
      has_reported = true
      device:set_field(zone_has_reported_field(endpoint_id), true, { persist = true })
    end

    if has_reported and latest_boolean ~= nil then
      device:set_field(zone_state_field(endpoint_id), latest_boolean)
    end
  end

  -- Seed duplicate suppression from the platform's current main state. A later
  -- recalculation will still correct it if the restored genuine zone states
  -- imply a different aggregate value.
  local latest_aggregate = get_latest_presence_state(device, "main")
  if presence_value_to_boolean(latest_aggregate) ~= nil then
    device:set_field(AGGREGATE_STATE_FIELD, latest_aggregate)
  end
end

local function emit_aggregate_presence(device)
  local any_known = false
  local any_present = false

  for _, endpoint_id in ipairs(ZONE_ENDPOINTS) do
    local state = device:get_field(zone_state_field(endpoint_id))
    if state ~= nil then
      any_known = true
      if state then
        any_present = true
      end
    end
  end

  -- Do not let synthetic UI defaults participate in aggregation. After at
  -- least one genuine zone report is known, zones that have never reported are
  -- ignored. This prevents unconfigured outputs from keeping main stuck.
  if not any_known then
    return
  end

  local aggregate_state = any_present and "present" or "not present"
  if device:get_field(AGGREGATE_STATE_FIELD) ~= aggregate_state then
    device:set_field(AGGREGATE_STATE_FIELD, aggregate_state)
    device:emit_event(capabilities.presenceSensor.presence(aggregate_state))
  end
end

local function occupancy_handler(driver, device, ib, response)
  local component_id = ZONE_COMPONENT_BY_ENDPOINT[ib.endpoint_id]
  if component_id == nil then
    device.log.warn_with({ hub_logs = true }, string.format(
      "Ignoring Occupancy report from unexpected endpoint %s", tostring(ib.endpoint_id)
    ))
    return
  end

  local value = ib.data and ib.data.value
  if value == nil then
    device.log.warn_with({ hub_logs = true }, string.format(
      "Ignoring null Occupancy report from endpoint %d", ib.endpoint_id
    ))
    return
  end

  -- Occupancy is a bitmap8. Bit 0 represents the occupied state. The modulo
  -- test is equivalent to checking (value & 0x01) for all valid bitmap8 values.
  local is_present = (value % 2) == 1

  device.log.debug(string.format(
    "MS605 Occupancy report: endpoint=%d component=%s value=%s present=%s",
    ib.endpoint_id,
    component_id,
    tostring(value),
    tostring(is_present)
  ))

  device:set_field(zone_state_field(ib.endpoint_id), is_present)
  if device:get_field(zone_has_reported_field(ib.endpoint_id)) ~= true then
    device:set_field(zone_has_reported_field(ib.endpoint_id), true, { persist = true })
  end

  device:emit_event_for_endpoint(
    ib.endpoint_id,
    capabilities.presenceSensor.presence(is_present and "present" or "not present")
  )

  emit_aggregate_presence(device)
end

local function illuminance_handler(driver, device, ib, response)
  local value = ib.data and ib.data.value
  if value == nil or value == 0xFFFF then
    return
  end

  -- Matter Illuminance Measurement uses a logarithmic representation:
  -- lux = 10 ^ ((MeasuredValue - 1) / 10000).
  local lux = math.floor(10 ^ ((value - 1) / 10000))
  device:emit_event_for_endpoint(
    ib.endpoint_id,
    capabilities.illuminanceMeasurement.illuminance(lux)
  )
end

local function battery_handler(driver, device, ib, response)
  local value = ib.data and ib.data.value
  if value == nil or value > 200 then
    return
  end

  -- Matter BatPercentRemaining is expressed in half-percent units.
  local percentage = math.floor(value / 2.0 + 0.5)
  percentage = math.max(0, math.min(100, percentage))
  device:emit_event(capabilities.battery.battery(percentage))
end

local function build_refresh_request(device)
  local request = clusters.OccupancySensing.attributes.Occupancy:read(device, ZONE_ENDPOINTS[1])
  for index = 2, #ZONE_ENDPOINTS do
    request:merge(
      clusters.OccupancySensing.attributes.Occupancy:read(device, ZONE_ENDPOINTS[index])
    )
  end
  request:merge(
    clusters.IlluminanceMeasurement.attributes.MeasuredValue:read(device, 1)
  )
  request:merge(
    clusters.PowerSource.attributes.BatPercentRemaining:read(device, 1)
  )
  return request
end

local function send_refresh_request(device, reason)
  device.log.debug(string.format("Sending merged MS605 refresh request (%s)", reason or "manual"))
  device:send(build_refresh_request(device))
end

local function refresh_handler(driver, device, command)
  -- Send one merged Interaction Model request. This is more reliable for a
  -- sleepy ICD than five separate requests during a short active window.
  send_refresh_request(device, "manual")
end

local function emit_synthetic_presence_if_missing(device, component_id, endpoint_id)
  if get_latest_presence_state(device, component_id) ~= nil then
    return
  end

  -- A genuine report may have arrived before the platform state cache becomes
  -- visible to this callback. The runtime field prevents it being overwritten.
  if endpoint_id ~= nil and device:get_field(zone_state_field(endpoint_id)) ~= nil then
    return
  end
  if endpoint_id == nil and device:get_field(AGGREGATE_STATE_FIELD) ~= nil then
    return
  end

  device.log.debug(string.format(
    "Initializing missing MS605 presence state for component %s to not present",
    component_id
  ))

  local event = capabilities.presenceSensor.presence(
    "not present",
    { state_change = false }
  )

  if endpoint_id ~= nil then
    -- The synthetic marker lets later driver starts distinguish this UI-only
    -- default from a genuine previous Matter report.
    device:set_field(zone_synthetic_state_field(endpoint_id), true, { persist = true })
    device:emit_event_for_endpoint(endpoint_id, event)
  else
    device:emit_event(event)
  end
end

local function initialize_missing_presence_states(device)
  for _, endpoint_id in ipairs(ZONE_ENDPOINTS) do
    emit_synthetic_presence_if_missing(
      device,
      ZONE_COMPONENT_BY_ENDPOINT[endpoint_id],
      endpoint_id
    )
  end
  emit_synthetic_presence_if_missing(device, "main", nil)
end

local function schedule_synthetic_initialization(device)
  local existing_timer = device:get_field(SYNTHETIC_INIT_TIMER_FIELD)
  if existing_timer ~= nil then
    device.thread:cancel_timer(existing_timer)
  end

  local timer
  timer = device.thread:call_with_delay(SYNTHETIC_INIT_DELAY_SECONDS, function()
    device:set_field(SYNTHETIC_INIT_TIMER_FIELD, nil)
    initialize_missing_presence_states(device)
  end)
  device:set_field(SYNTHETIC_INIT_TIMER_FIELD, timer)
end

local function initialize_device(device, restore_presence_state)
  install_endpoint_mapping(device)
  if restore_presence_state then
    restore_runtime_presence_state(device)
    emit_aggregate_presence(device)
  end
  device:subscribe()
  send_refresh_request(device, "initialization")
  schedule_synthetic_initialization(device)
end

local lifecycle_handlers = {}

function lifecycle_handlers.init(driver, device)
  device.log.info(string.format(
    "Initializing Meross MS605 multi-zone presence sensor, driver %s",
    DRIVER_VERSION
  ))
  initialize_device(device, true)
end

function lifecycle_handlers.do_configure(driver, device)
  -- The subscription was established during init. Keep this handler minimal
  -- and, unlike the generic Matter Sensor driver, do not re-profile the MS605.
  install_endpoint_mapping(device)
end

function lifecycle_handlers.driver_switched(driver, device)
  install_endpoint_mapping(device)
  device:try_update_metadata({ profile = PROFILE_NAME })
  device:try_update_metadata({ provisioning_state = "PROVISIONED" })
end

function lifecycle_handlers.info_changed(driver, device, event, args)
  local old_profile = args.old_st_store and args.old_st_store.profile
  if old_profile == nil or old_profile.id ~= device.profile.id then
    initialize_device(device, false)
  end
end

local driver_template = {
  lifecycle_handlers = {
    init = lifecycle_handlers.init,
    doConfigure = lifecycle_handlers.do_configure,
    driverSwitched = lifecycle_handlers.driver_switched,
    infoChanged = lifecycle_handlers.info_changed,
  },
  matter_handlers = {
    attr = {
      [clusters.OccupancySensing.ID] = {
        [clusters.OccupancySensing.attributes.Occupancy.ID] = occupancy_handler,
      },
      [clusters.IlluminanceMeasurement.ID] = {
        [clusters.IlluminanceMeasurement.attributes.MeasuredValue.ID] = illuminance_handler,
      },
      [clusters.PowerSource.ID] = {
        [clusters.PowerSource.attributes.BatPercentRemaining.ID] = battery_handler,
      },
    },
  },
  subscribed_attributes = {
    [capabilities.presenceSensor.ID] = {
      clusters.OccupancySensing.attributes.Occupancy,
    },
    [capabilities.illuminanceMeasurement.ID] = {
      clusters.IlluminanceMeasurement.attributes.MeasuredValue,
    },
    [capabilities.battery.ID] = {
      clusters.PowerSource.attributes.BatPercentRemaining,
    },
  },
  capability_handlers = {
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = refresh_handler,
    },
  },
  supported_capabilities = {
    capabilities.presenceSensor,
    capabilities.illuminanceMeasurement,
    capabilities.battery,
    capabilities.refresh,
  },
  shared_device_thread_enabled = true,
}

local driver = MatterDriver(DRIVER_NAME, driver_template)
driver:run()
