-- Community SmartThings Edge Driver
-- SONOFF Hydro ONE Zigbee smart water valves
-- Full Hydro ONE: SWV-ZFE / SWV-ZFU with flow meter.
-- Hydro ONE Lite: SWV-ZNE / SWV-ZNU without flow meter.
-- Hydro DUO: SWV-ZF2 / SWV-ZF2E / SWV-ZF2U dual-channel valve with flow meter.
-- Full and Lite models keep their proven behavior; Hydro DUO uses a separate
-- two-component profile that maps channel 1 to main and channel 2 to channel2.

local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"
local clusters = require "st.zigbee.zcl.clusters"
local zcl_global_commands = require "st.zigbee.zcl.global_commands"
local data_types = require "st.zigbee.data_types"
local device_management = require "st.zigbee.device_management"

local utils = require "sonoff_utils"

local Basic = clusters.Basic
local OnOff = clusters.OnOff
local PowerConfiguration = clusters.PowerConfiguration
local PollControl = clusters.PollControl

local hydroTimedWatering = capabilities["oceancircle09600.hydroTimedWatering"]
local hydroIrrigationStatus = capabilities["oceancircle09600.hydroIrrigationStatus"]
local hydroLiteIrrigationStatus = capabilities["oceancircle09600.hydroLiteIrrigationStatus"]
local hydroValveAlerts = capabilities["oceancircle09600.hydroValveAlerts"]

local DRIVER_VERSION = "1.4.0-alpha29"

local PREFERENCE_DEFAULTS = {
  childLock = "unlocked",
  shortageAlarm = "disabled",
  leakAlarm = "disabled",
  frostAlarm = "disabled",
  shortageAutoClose = "disabled",
  leakAutoClose = "disabled",
  shortageDuration = 1,
  leakDuration = 1,
  frostThreshold = 5,
  manualDuration = 10,
}

-- Optional SONOFF private-setting synchronization is deliberately isolated
-- from standard valve control. Open, Close, and custom timed watering never
-- call or wait for these functions.
local write_manual_default_duration
local process_manual_sync_readback

local function debug_log(device, message, ...)
  if device and device.preferences and device.preferences.debugLogging then
    local ok, formatted = pcall(string.format, "SONOFF Hydro ONE: " .. message, ...)
    if ok then
      print(formatted)
    else
      print("SONOFF Hydro ONE: " .. tostring(message))
    end
  end
end

local function bytes_to_hex(bytes)
  local out = {}
  if type(bytes) ~= "table" then return tostring(bytes) end
  for i, b in ipairs(bytes) do
    out[i] = string.format("%02X", b & 0xFF)
  end
  return table.concat(out, " ")
end



local function get_profile_name(device)
  local profile = device and device.profile
  if type(profile) == "string" then return profile end
  if type(profile) == "table" then
    if type(profile.name) == "string" then return profile.name end
    if type(profile.id) == "string" then return profile.id end
  end
  return nil
end

local function get_model(device)
  local ok, model = pcall(function()
    if device and device.get_model then return device:get_model() end
    return nil
  end)
  if ok and type(model) == "string" then return model end
  return nil
end

local function is_lite_device(device)
  local profile = get_profile_name(device)
  if profile == "sonoff-hydro-one-lite" then return true end
  local model = get_model(device)
  return model == "SWV-ZNE" or model == "SWV-ZNU"
end

local function is_duo_device(device)
  local profile = get_profile_name(device)
  if profile == "sonoff-hydro-duo" then return true end
  local model = get_model(device)
  return model == "SWV-ZF2" or model == "SWV-ZF2E" or model == "SWV-ZF2U"
end


local function normalize_firmware_version(value)
  if type(value) == "table" then
    value = value.value or value.data
  end
  if value == nil then return nil end
  local version = tostring(value):gsub("%z", "")
  version = version:match("^%s*(.-)%s*$") or version
  if version == "" then return nil end
  return version
end

local function firmware_version_parts(version)
  version = normalize_firmware_version(version)
  if version == nil then return nil end

  local major, minor, patch = version:match("(%d+)%.(%d+)%.(%d+)")
  if major ~= nil then return tonumber(major), tonumber(minor), tonumber(patch) end

  local compact_major, compact_tail = version:match("^(%d+)%.(%d+)$")
  if compact_major ~= nil then
    if #compact_tail == 2 then
      return tonumber(compact_major), tonumber(compact_tail:sub(1, 1)), tonumber(compact_tail:sub(2, 2))
    end
    return tonumber(compact_major), tonumber(compact_tail), 0
  end

  local hex = version:match("^0[xX]([0-9A-Fa-f]+)$")
  if hex ~= nil and #hex >= 4 then
    local tail = hex:sub(-4)
    if tail:match("^%d%d%d%d$") then
      return tonumber(tail:sub(1, 1)), tonumber(tail:sub(2, 2)), tonumber(tail:sub(3, 4))
    end
  end
  return nil
end

local function version_at_least(version, req_major, req_minor, req_patch)
  local major, minor, patch = firmware_version_parts(version)
  if major == nil then return false end
  if major ~= req_major then return major > req_major end
  if minor ~= req_minor then return minor > req_minor end
  return patch >= req_patch
end

local function firmware_supports_unified_water_flow(device, version)
  version = version or (device and device:get_field("firmware_version"))
  if is_duo_device(device) then return version_at_least(version, 1, 0, 9) end
  return version_at_least(version, 1, 1, 0)
end

local function duo_component_ids(device)
  if is_duo_device(device) then
    return { "main", "channel2" }
  end
  return { "main" }
end

local function normalize_component_id(component_id)
  if component_id == nil or component_id == "" then return "main" end
  return tostring(component_id)
end

local function component_to_endpoint(device_or_component, maybe_component)
  local component_id = maybe_component
  if component_id == nil and type(device_or_component) == "string" then
    component_id = device_or_component
  end
  component_id = normalize_component_id(component_id)
  if component_id == "channel2" then return 2 end
  return 1
end

local function endpoint_to_component(device_or_endpoint, maybe_endpoint)
  local endpoint = maybe_endpoint
  if endpoint == nil then
    if type(device_or_endpoint) == "number" then
      endpoint = device_or_endpoint
    elseif type(device_or_endpoint) == "table" and type(device_or_endpoint.value) == "number" then
      endpoint = device_or_endpoint.value
    end
  elseif type(endpoint) == "table" and type(endpoint.value) == "number" then
    endpoint = endpoint.value
  end
  if endpoint == 2 then return "channel2" end
  return "main"
end

local function setup_component_mapping(device)
  if device == nil then return end
  if device.set_component_to_endpoint_fn then
    device:set_component_to_endpoint_fn(component_to_endpoint)
  end
  if device.set_endpoint_to_component_fn then
    device:set_endpoint_to_component_fn(endpoint_to_component)
  end
end

local function get_command_component(command)
  if command and command.component then
    return normalize_component_id(command.component)
  end
  return "main"
end

local function get_rx_endpoint(zb_rx)
  local candidates = {
    zb_rx and zb_rx.address_header and zb_rx.address_header.src_endpoint,
    zb_rx and zb_rx.address_header and zb_rx.address_header.source_endpoint,
    zb_rx and zb_rx.src_endpoint,
    zb_rx and zb_rx.source_endpoint,
  }
  for _, endpoint in ipairs(candidates) do
    if type(endpoint) == "number" then return endpoint end
    if type(endpoint) == "table" and type(endpoint.value) == "number" then return endpoint.value end
  end
  return 1
end

local function component_from_rx(device, zb_rx)
  if not is_duo_device(device) then return "main" end
  return endpoint_to_component(device, get_rx_endpoint(zb_rx))
end


local function shared_private_endpoint_is_valid(device, endpoint, source)
  if not is_duo_device(device) then return true end
  local ep = tonumber(endpoint) or 1
  if ep == 1 then return true end
  debug_log(device, "ignoring shared private attribute from endpoint=%s source=%s", tostring(ep), tostring(source or "unknown"))
  return false
end

local function emit_capability_event(device, event, component_id)
  if event == nil then return end
  if is_duo_device(device) then
    setup_component_mapping(device)
    local endpoint = component_to_endpoint(device, component_id)
    local ok, err = pcall(function()
      device:emit_event_for_endpoint(endpoint, event)
    end)
    if ok then return end
    print("SONOFF Hydro ONE: emit_event_for_endpoint failed, falling back to main event: " .. tostring(err))
  end
  device:emit_event(event)
end

local function send_zcl_to_component(device, component_id, msg)
  component_id = normalize_component_id(component_id)
  if is_duo_device(device) and device.send_to_component then
    setup_component_mapping(device)
    device:send_to_component(component_id, msg)
  else
    device:send(msg)
  end
end

local function irrigation_status_capability(device)
  if is_lite_device(device) then
    return hydroLiteIrrigationStatus
  end
  return hydroIrrigationStatus
end

local function guarded(name, fn)
  return function(driver, device, command)
    local ok, err = pcall(fn, driver, device, command)
    if not ok then
      print("SONOFF Hydro ONE: command handler failed (" .. tostring(name) .. "): " .. tostring(err))
    end
  end
end

local function safe_emit(device, capability, attribute_name, value, unit, component_id)
  if capability == nil or capability[attribute_name] == nil then
    return
  end
  local ok, event_or_err
  if unit ~= nil then
    ok, event_or_err = pcall(function()
      return capability[attribute_name]({ value = value, unit = unit })
    end)
  else
    ok, event_or_err = pcall(function()
      return capability[attribute_name]({ value = value })
    end)
  end
  if ok and event_or_err ~= nil then
    emit_capability_event(device, event_or_err, component_id)
  else
    print("SONOFF Hydro ONE: failed to emit " .. tostring(attribute_name) .. ": " .. tostring(event_or_err))
  end
end

local function emit_valve_state(device, is_open, component_id)
  component_id = normalize_component_id(component_id)
  if is_open then
    emit_capability_event(device, capabilities.switch.switch.on(), component_id)
    emit_capability_event(device, capabilities.valve.valve.open(), component_id)
    safe_emit(device, irrigation_status_capability(device), "valveWorkState", "working", nil, component_id)
  else
    emit_capability_event(device, capabilities.switch.switch.off(), component_id)
    emit_capability_event(device, capabilities.valve.valve.closed(), component_id)
    safe_emit(device, irrigation_status_capability(device), "valveWorkState", "idle", nil, component_id)
  end
end

local function timed_field_name(base, component_id)
  return base .. ":" .. normalize_component_id(component_id)
end

local function set_timed_watering_state(device, state, component_id)
  safe_emit(device, hydroTimedWatering, "timedWatering", state, nil, component_id)
end

local function next_timed_session_token(device, component_id)
  local key = timed_field_name("timed_session_token", component_id)
  local token = (device:get_field(key) or 0) + 1
  device:set_field(key, token)
  if normalize_component_id(component_id) == "main" then device:set_field("timed_session_token", token) end
  return token
end

local function set_timed_session_token(device, component_id, token)
  device:set_field(timed_field_name("timed_session_token", component_id), token)
  if normalize_component_id(component_id) == "main" then device:set_field("timed_session_token", token) end
end

local function get_timed_session_token(device, component_id)
  return device:get_field(timed_field_name("timed_session_token", component_id)) or 0
end

local function set_timed_session_active(device, component_id, active)
  local value = active == true
  device:set_field(timed_field_name("timed_session_active", component_id), value)
  if normalize_component_id(component_id) == "main" then device:set_field("timed_session_active", value) end
end

local function is_timed_session_active(device, component_id)
  return device:get_field(timed_field_name("timed_session_active", component_id)) == true
end

local function set_timed_recovery_required(device, component_id, required)
  device:set_field(timed_field_name("timed_recovery_required", component_id), required == true, { persist = true })
end

local function timed_recovery_required(device, component_id)
  return device:get_field(timed_field_name("timed_recovery_required", component_id)) == true
end

local function cancel_timed_session(device, emit_idle, component_id, clear_recovery)
  component_id = normalize_component_id(component_id)
  next_timed_session_token(device, component_id)
  set_timed_session_active(device, component_id, false)
  if clear_recovery ~= false then set_timed_recovery_required(device, component_id, false) end
  if emit_idle then set_timed_watering_state(device, "idle", component_id) end
end

local function cancel_all_timed_sessions(device, emit_idle, clear_recovery)
  for _, component_id in ipairs(duo_component_ids(device)) do
    cancel_timed_session(device, emit_idle, component_id, clear_recovery)
  end
end

local function close_other_duo_channel(device, component_id)
  if not is_duo_device(device) then return end
  local other_component = component_id == "channel2" and "main" or "channel2"
  local sent, send_err = pcall(function()
    send_zcl_to_component(device, other_component, OnOff.server.commands.Off(device))
  end)
  if not sent then
    print("SONOFF Hydro ONE: failed to queue opposite-channel Off before Open: " .. tostring(send_err))
    return
  end
  local ok, err = pcall(function()
    cancel_timed_session(device, true, other_component, true)
    emit_valve_state(device, false, other_component)
  end)
  if not ok then print("SONOFF Hydro ONE: opposite-channel state cleanup failed: " .. tostring(err)) end
end

local function send_on(device, component_id)
  component_id = normalize_component_id(component_id)
  close_other_duo_channel(device, component_id)

  -- Reliability rule: queue the same standard Zigbee On command used by the
  -- generic SmartThings driver before doing any bookkeeping or UI updates.
  send_zcl_to_component(device, component_id, OnOff.server.commands.On(device))
  local ok, err = pcall(function()
    cancel_all_timed_sessions(device, true, true)
    emit_valve_state(device, true, component_id)
  end)
  if not ok then print("SONOFF Hydro ONE: post-On state update failed: " .. tostring(err)) end
  debug_log(device, "standard On queued component=%s", tostring(component_id))
end

local function send_off(device, component_id)
  component_id = normalize_component_id(component_id)

  -- Reliability rule: queue standard Off first. Timer cleanup and optimistic
  -- state updates happen only afterwards and cannot block the physical command.
  send_zcl_to_component(device, component_id, OnOff.server.commands.Off(device))
  local ok, err = pcall(function()
    cancel_timed_session(device, true, component_id, true)
    emit_valve_state(device, false, component_id)
  end)
  if not ok then print("SONOFF Hydro ONE: post-Off state update failed: " .. tostring(err)) end
  debug_log(device, "standard Off queued component=%s", tostring(component_id))
end

local function send_timed_open(device, minutes, component_id)
  component_id = normalize_component_id(component_id)
  local m = utils.clamp_int(minutes, 1, 719, 1)
  local seconds = m * 60

  if not (device.thread and device.thread.call_with_delay) then
    print("SONOFF Hydro ONE: timed watering was not started because the Edge timer API is unavailable")
    return
  end

  close_other_duo_channel(device, component_id)
  local token = get_timed_session_token(device, component_id) + 1
  local committed = false

  local scheduled, schedule_err = pcall(function()
    device.thread:call_with_delay(seconds, function()
      if not committed then return end
      if is_timed_session_active(device, component_id) and get_timed_session_token(device, component_id) == token then
        debug_log(device, "timed watering elapsed component=%s token=%s; queueing Off", tostring(component_id), tostring(token))
        local ok, err = pcall(send_off, device, component_id)
        if not ok then
          print("SONOFF Hydro ONE: timed watering failed to queue Off: " .. tostring(err))
          set_timed_recovery_required(device, component_id, true)
        end
      end
    end)
  end)
  if not scheduled then
    print("SONOFF Hydro ONE: timed watering was not started because its close timer could not be scheduled: " .. tostring(schedule_err))
    return
  end

  -- Custom timed watering intentionally uses the same proven standard On as
  -- normal control. The SmartThings timer supplies the additional auto-close.
  send_zcl_to_component(device, component_id, OnOff.server.commands.On(device))
  set_timed_session_token(device, component_id, token)
  set_timed_session_active(device, component_id, true)
  set_timed_recovery_required(device, component_id, true)
  committed = true
  local ui_ok, ui_err = pcall(function()
    safe_emit(device, hydroTimedWatering, "timedOpenMinutes", m, "min", component_id)
    set_timed_watering_state(device, "running", component_id)
    emit_valve_state(device, true, component_id)
  end)
  if not ui_ok then print("SONOFF Hydro ONE: timed-watering state update failed: " .. tostring(ui_err)) end
  debug_log(device, "timed watering started %s min component=%s token=%s", tostring(m), tostring(component_id), tostring(token))
end

local function read_standard_attributes(device)
  send_zcl_to_component(device, "main", Basic.attributes.SWBuildID:read(device))
  send_zcl_to_component(device, "main", OnOff.attributes.OnOff:read(device))
  if is_duo_device(device) then send_zcl_to_component(device, "channel2", OnOff.attributes.OnOff:read(device)) end
  send_zcl_to_component(device, "main", PowerConfiguration.attributes.BatteryPercentageRemaining:read(device))
end

local function read_private_attribute(device, attr_id, component_id)
  component_id = normalize_component_id(component_id)
  if attr_id == utils.ATTR_MANUAL_DEFAULT_SETTINGS
    or attr_id == utils.ATTR_VALVE_ALARM_SETTINGS
    or attr_id == utils.ATTR_UNIT_OF_WATER_FLOW then
    component_id = "main"
  end

  local builder = utils.custom_read_attribute
  local args = { device, utils.EWELINK_CLUSTER_ID, attr_id, utils.SONOFF_MFG_CODE }
  if attr_id == utils.ATTR_MANUAL_DEFAULT_SETTINGS or attr_id == utils.ATTR_UNIT_OF_WATER_FLOW then
    builder = utils.standard_read_attribute
    args = { device, utils.EWELINK_CLUSTER_ID, attr_id }
  end

  local ok, msg_or_err = pcall(builder, table.unpack(args))
  if ok and msg_or_err ~= nil then
    send_zcl_to_component(device, component_id, msg_or_err)
  else
    print(string.format("SONOFF Hydro ONE: failed to build private read for 0x%04X: %s", attr_id, tostring(msg_or_err)))
  end
end

local function firmware_version_attr_handler(driver, device, value, zb_rx)
  local version = normalize_firmware_version(value)
  if version == nil then return end
  local previous = device:get_field("firmware_version")
  device:set_field("firmware_version", version, { persist = true })
  device:emit_event(capabilities.firmwareUpdate.currentVersion({ value = version }))
  debug_log(device, "device firmware version=%s", version)

  if firmware_supports_unified_water_flow(device, version)
    and not (device.preferences and device.preferences.readPrivateOnRefresh == false) then
    local probed = device:get_field("water_flow_unit_probe_firmware")
    if probed ~= version or previous ~= version or device:get_field("water_flow_unit_code") == nil then
      device:set_field("water_flow_unit_probe_firmware", version, { persist = true })
      read_private_attribute(device, utils.ATTR_UNIT_OF_WATER_FLOW, "main")
    end
  end
end

local function read_private_attributes(device)
  if device.preferences and device.preferences.readPrivateOnRefresh == false then
    return
  end

  if is_duo_device(device) then
    -- Hydro DUO uses endpoint 1 for channel 1 and endpoint 2 for channel 2.
    -- Z2M exposes duration per endpoint while volume is device-wide because the
    -- hardware permits only one channel to run at a time.
    read_private_attribute(device, utils.ATTR_CHILD_LOCK, "main")
    read_private_attribute(device, utils.ATTR_MANUAL_DEFAULT_SETTINGS, "main")
    read_private_attribute(device, utils.ATTR_REAL_TIME_IRRIGATION_DURATION, "main")
    read_private_attribute(device, utils.ATTR_REAL_TIME_IRRIGATION_DURATION, "channel2")
    read_private_attribute(device, utils.ATTR_REAL_TIME_IRRIGATION_VOLUME, "main")
    read_private_attribute(device, utils.ATTR_VALVE_ABNORMAL_STATE, "main")
    read_private_attribute(device, utils.ATTR_VALVE_WORK_STATE, "main")
    read_private_attribute(device, utils.ATTR_VALVE_WORK_STATE, "channel2")
    read_private_attribute(device, utils.ATTR_HOUR_IRRIGATION_DURATION, "main")
    read_private_attribute(device, utils.ATTR_HOUR_IRRIGATION_DURATION, "channel2")
    read_private_attribute(device, utils.ATTR_HOUR_IRRIGATION_VOLUME, "main")
    read_private_attribute(device, utils.ATTR_VALVE_ALARM_SETTINGS, "main")
    if firmware_supports_unified_water_flow(device) then
      read_private_attribute(device, utils.ATTR_UNIT_OF_WATER_FLOW, "main")
    end
    return
  end

  local attrs

  if is_lite_device(device) then
    -- Hydro ONE Lite has no flow meter, so keep its private reads duration-only.
    attrs = {
      utils.ATTR_CHILD_LOCK,
      utils.ATTR_MANUAL_DEFAULT_SETTINGS,
      utils.ATTR_REAL_TIME_IRRIGATION_DURATION,
      utils.ATTR_VALVE_WORK_STATE,
      utils.ATTR_HOUR_IRRIGATION_DURATION,
    }
  else
    -- Keep the known-good full Hydro ONE read order from v1.0.1.
    -- This avoids changing the production-confirmed flow-meter path while adding Lite support.
    attrs = {
      utils.ATTR_CHILD_LOCK,
      utils.ATTR_MANUAL_DEFAULT_SETTINGS,
      utils.ATTR_REAL_TIME_IRRIGATION_DURATION,
      utils.ATTR_REAL_TIME_IRRIGATION_VOLUME,
      utils.ATTR_VALVE_ABNORMAL_STATE,
      utils.ATTR_VALVE_WORK_STATE,
      utils.ATTR_HOUR_IRRIGATION_DURATION,
      utils.ATTR_HOUR_IRRIGATION_VOLUME,
      utils.ATTR_VALVE_ALARM_SETTINGS,
    }
  end

  if firmware_supports_unified_water_flow(device) then
    table.insert(attrs, utils.ATTR_UNIT_OF_WATER_FLOW)
  end
  for _, attr_id in ipairs(attrs) do
    read_private_attribute(device, attr_id, "main")
  end
end

local function write_child_lock(device, locked)
  local ok, msg_or_err = pcall(
    utils.custom_write_attribute,
    device,
    utils.EWELINK_CLUSTER_ID,
    utils.ATTR_CHILD_LOCK,
    data_types.Boolean,
    locked,
    utils.SONOFF_MFG_CODE
  )
  if ok and msg_or_err ~= nil then
    device:send(msg_or_err)
    device:set_field("child_lock_state", locked and "locked" or "unlocked")
    debug_log(device, "child lock write requested: %s", locked and "locked" or "unlocked")
  else
    print("SONOFF Hydro ONE: failed to write child lock: " .. tostring(msg_or_err))
  end
end


local MANUAL_SYNC_TIMEOUT_SECONDS = 8

local function desired_manual_duration(device)
  local value = device and device.preferences and device.preferences.manualDuration
  return utils.clamp_int(value, 1, 719, PREFERENCE_DEFAULTS.manualDuration)
end

local function manual_duration_is_user_configured(device)
  if device:get_field("manual_duration_user_configured") == true then return true end
  if device:get_field("manual_sync_target") ~= nil then return true end
  local selected = desired_manual_duration(device)
  return selected ~= PREFERENCE_DEFAULTS.manualDuration
end

local function next_manual_sync_token(device)
  local token = (tonumber(device:get_field("manual_sync_token")) or 0) + 1
  device:set_field("manual_sync_token", token)
  return token
end

local function clear_manual_sync(device, status, err, confirmed)
  next_manual_sync_token(device)
  device:set_field("manual_default_last_sync_status", status, { persist = true })
  device:set_field("manual_default_last_sync_error", err)
  if confirmed ~= nil then
    device:set_field("manual_default_confirmed_duration", confirmed, { persist = true })
  end
  device:set_field("manual_sync_phase", nil)
  device:set_field("manual_sync_target", nil, { persist = true })
end

local function schedule_manual_sync_timeout(device, target, token)
  if not (device.thread and device.thread.call_with_delay) then return end
  local ok, err = pcall(function()
    device.thread:call_with_delay(MANUAL_SYNC_TIMEOUT_SECONDS, function()
      if tonumber(device:get_field("manual_sync_token")) ~= token then return end
      if tonumber(device:get_field("manual_sync_target")) ~= target then return end
      if device:get_field("manual_sync_phase") == nil then return end
      clear_manual_sync(device, "failed", "timed out waiting for 0x501D readback")
      print("SONOFF Hydro ONE: device-side watering limit synchronization timed out; basic Open/Close is unaffected")
    end)
  end)
  if not ok then
    debug_log(device, "could not schedule 0x501D synchronization timeout: %s", tostring(err))
  end
end

local function start_manual_duration_sync(device, minutes, reason, send_read, restart_active)
  local value = utils.clamp_int(minutes, 1, 719, PREFERENCE_DEFAULTS.manualDuration)
  local phase = device:get_field("manual_sync_phase")
  local current_target = tonumber(device:get_field("manual_sync_target"))
  if not restart_active and phase ~= nil and current_target == value then return false end

  local token = next_manual_sync_token(device)
  device:set_field("manual_sync_target", value, { persist = true })
  device:set_field("manual_sync_phase", "read")
  device:set_field("manual_default_last_sync_status", "pending", { persist = true })
  device:set_field("manual_default_last_sync_error", nil)
  debug_log(device, "starting independent 0x501D synchronization target=%s reason=%s; standard valve commands remain independent", tostring(value), tostring(reason or "unspecified"))

  if send_read ~= false then
    local ok, err = pcall(read_private_attribute, device, utils.ATTR_MANUAL_DEFAULT_SETTINGS, "main")
    if not ok then
      clear_manual_sync(device, "failed", "0x501D read request failed: " .. tostring(err))
      return false
    end
  end

  schedule_manual_sync_timeout(device, value, token)
  return true
end

local function ensure_manual_duration_sync(device, reason, send_read, force)
  if not manual_duration_is_user_configured(device) then return false end
  local target = desired_manual_duration(device)
  local confirmed = tonumber(device:get_field("manual_default_confirmed_duration"))
  local status = device:get_field("manual_default_last_sync_status")
  if not force and status == "verified" and confirmed == target then return false end
  return start_manual_duration_sync(device, target, reason, send_read, force == true)
end

write_manual_default_duration = function(device, minutes)
  local value = utils.clamp_int(minutes, 1, 719, PREFERENCE_DEFAULTS.manualDuration)
  device:set_field("manual_duration_user_configured", true, { persist = true })
  start_manual_duration_sync(device, value, "preference changed", true, true)
end

local function default_alarm_settings()
  return {
    byte0 = 0x00,
    water_shortage_duration = 1,
    water_leak_duration = 1,
    frost_threshold = 5,
  }
end

local function clone_alarm_settings(settings)
  settings = settings or default_alarm_settings()
  return {
    byte0 = utils.clamp_int(settings.byte0 or 0, 0, 0xFF, 0),
    water_shortage_duration = utils.clamp_int(settings.water_shortage_duration or 1, 1, 10, 1),
    water_leak_duration = utils.clamp_int(settings.water_leak_duration or 1, 1, 3, 1),
    frost_threshold = utils.clamp_int(settings.frost_threshold or 5, 0, 60, 5),
  }
end

local function get_alarm_settings(device)
  return device:get_field("valve_alarm_settings")
end

local function get_alarm_settings_or_default(device)
  return get_alarm_settings(device) or default_alarm_settings()
end

local function alarm_settings_loaded(device)
  return device:get_field("valve_alarm_settings_loaded") == true
end

local function request_alarm_settings_read(device, reason)
  debug_log(device, "valve_alarm_settings 0x5020 not available yet; reading before write%s", reason and (" (" .. reason .. ")") or "")
  read_private_attribute(device, utils.ATTR_VALVE_ALARM_SETTINGS)
end

local function queue_alarm_settings_update(device, pending_update, reason)
  local pending = device:get_field("pending_valve_alarm_settings_update") or {}
  table.insert(pending, pending_update)
  device:set_field("pending_valve_alarm_settings_update", pending)
  request_alarm_settings_read(device, reason)
end

local function store_alarm_settings(device, settings)
  -- Keep the decoded settings in memory only. Persisting Lua tables is not
  -- necessary here and may be less portable across Edge runtime versions.
  -- After a driver restart, the first settings write will queue behind a fresh
  -- 0x5020 readback again, which is safer than writing stale persisted data.
  device:set_field("valve_alarm_settings", settings)
  device:set_field("valve_alarm_settings_loaded", true)
end

local function emit_alarm_settings(device, settings)
  -- Option A UI model: 0x5020 valve settings are preferences, not a visible custom capability.
  -- Readback is kept in runtime state and debug logs. Preferences represent the requested
  -- configuration; they are not automatically overwritten from device readback.
  debug_log(
    device,
    "valve_alarm_settings readback: shortage_alarm=%s leak_alarm=%s frost_alarm=%s shortage_auto_close=%s leak_auto_close=%s shortage_duration=%s leak_duration=%s frost_threshold=%s",
    utils.enabled_disabled((settings.byte0 & utils.ALARM_WATER_SHORTAGE) ~= 0),
    utils.enabled_disabled((settings.byte0 & utils.ALARM_WATER_LEAK) ~= 0),
    utils.enabled_disabled((settings.byte0 & utils.ALARM_FROST_PROTECTION) ~= 0),
    utils.enabled_disabled((settings.byte0 & utils.ALARM_WATER_SHORTAGE_AUTO_CLOSE) ~= 0),
    utils.enabled_disabled((settings.byte0 & utils.ALARM_WATER_LEAK_AUTO_CLOSE) ~= 0),
    tostring(settings.water_shortage_duration or 1),
    tostring(settings.water_leak_duration or 1),
    tostring(settings.frost_threshold or 0)
  )
end

local write_alarm_settings

local function apply_alarm_update_to_settings(settings, item)
  if item.kind == "bit" then
    settings.byte0 = utils.set_or_clear_bit(settings.byte0 or 0, item.bit, item.enabled)
  elseif item.kind == "duration" then
    settings[item.field] = utils.clamp_int(item.minutes, item.min_value, item.max_value, item.default_value)
  elseif item.kind == "frost" then
    settings.frost_threshold = utils.clamp_int(item.degrees_c, 0, 60, 5)
  end
end

local function apply_alarm_updates(device, updates, reason)
  if updates == nil or #updates == 0 then return end

  local settings = get_alarm_settings(device)
  if settings == nil then
    for _, item in ipairs(updates) do
      queue_alarm_settings_update(device, item, reason or "alarm settings update")
    end
    return
  end

  settings = clone_alarm_settings(settings)
  for _, item in ipairs(updates) do
    apply_alarm_update_to_settings(settings, item)
  end
  write_alarm_settings(device, settings)
end

local function apply_pending_alarm_settings_update(device)
  local pending = device:get_field("pending_valve_alarm_settings_update")
  if pending == nil then return end
  device:set_field("pending_valve_alarm_settings_update", nil)

  if pending.kind ~= nil then pending = { pending } end
  apply_alarm_updates(device, pending, "queued alarm settings update")
end

local function parse_alarm_settings(device, decoded_value)
  local bytes = utils.array_to_bytes(decoded_value)
  if #bytes < 4 then
    print("SONOFF Hydro ONE: valve_alarm_settings 0x5020 report too short: " .. tostring(#bytes) .. " byte(s)")
    return
  end
  local settings = {
    byte0 = bytes[1] or 0,
    water_shortage_duration = bytes[2] or 0,
    water_leak_duration = bytes[3] or 0,
    frost_threshold = bytes[4] or 0,
  }
  debug_log(device, "read valve_alarm_settings 0x5020 bytes: %s", bytes_to_hex(bytes))
  store_alarm_settings(device, settings)
  emit_alarm_settings(device, settings)
  apply_pending_alarm_settings_update(device)
end

function write_alarm_settings(device, settings)
  if not alarm_settings_loaded(device) then
    request_alarm_settings_read(device, "write requested before initial readback")
    return
  end

  -- Work on a sanitized copy. The object returned by get_alarm_settings() is
  -- stored in device field memory; mutating it before a successful send would
  -- make the UI cache look changed even if the ZCL write never left the driver.
  settings = clone_alarm_settings(settings)

  local bytes = {
    settings.byte0,
    settings.water_shortage_duration,
    settings.water_leak_duration,
    settings.frost_threshold,
  }

  debug_log(device, "writing valve_alarm_settings 0x5020 bytes: %s", bytes_to_hex(bytes))

  local ok_array, array_data = pcall(utils.build_uint8_array, bytes)
  local err = ok_array and nil or array_data
  if array_data == nil then
    print("SONOFF Hydro ONE: failed to build valve_alarm_settings array: " .. tostring(err))
    return
  end

  local ok, msg_or_err = pcall(
    utils.custom_write_attribute_data,
    device,
    utils.EWELINK_CLUSTER_ID,
    utils.ATTR_VALVE_ALARM_SETTINGS,
    array_data,
    utils.SONOFF_MFG_CODE
  )
  if not ok or msg_or_err == nil then
    print("SONOFF Hydro ONE: failed to build valve_alarm_settings 0x5020 write: " .. tostring(msg_or_err))
    return
  end

  local send_ok, send_err = pcall(function()
    device:send(msg_or_err)
  end)
  if not send_ok then
    print("SONOFF Hydro ONE: failed to send valve_alarm_settings 0x5020 write: " .. tostring(send_err))
    return
  end

  -- Optimistically update local state, then rely on the follow-up read/refresh to confirm.
  store_alarm_settings(device, settings)
  emit_alarm_settings(device, settings)

  local delay_ok, delay_err = pcall(function()
    if device.thread and device.thread.call_with_delay then
      device.thread:call_with_delay(2, function()
        read_private_attribute(device, utils.ATTR_VALVE_ALARM_SETTINGS)
      end)
    else
      read_private_attribute(device, utils.ATTR_VALVE_ALARM_SETTINGS)
    end
  end)
  if not delay_ok then
    print("SONOFF Hydro ONE: post-write valve_alarm_settings read scheduling failed: " .. tostring(delay_err))
  end
end

local function onoff_attr_handler(driver, device, value, zb_rx)
  local is_open = utils.to_bool(value)
  local component_id = component_from_rx(device, zb_rx)
  emit_valve_state(device, is_open, component_id)
  if is_open then
    if is_timed_session_active(device, component_id) then
      set_timed_watering_state(device, "running", component_id)
    else
      set_timed_watering_state(device, "idle", component_id)
    end
  else
    cancel_timed_session(device, true, component_id)
  end

  -- A standard state report proves the sleepy valve is awake. Retry only a
  -- previously configured, currently unverified device-side limit. This never
  -- delays or gates the On/Off command that caused the report.
  if manual_duration_is_user_configured(device)
    and device:get_field("manual_sync_phase") == nil
    and device:get_field("manual_default_last_sync_status") ~= "verified" then
    ensure_manual_duration_sync(device, "valve activity", true, true)
  end
end

local function battery_attr_handler(driver, device, value, zb_rx)
  local raw = utils.to_number(value)
  if raw == nil then return end
  -- Zigbee battery percentage remaining is reported in half-percent units.
  local percent = utils.clamp_int(raw / 2, 0, 100, 0)
  device:emit_event(capabilities.battery.battery(percent))
end

local function parse_abnormal_state(device, raw)
  if is_lite_device(device) then
    debug_log(device, "ignoring abnormal-state report on Lite model")
    return
  end
  local n = utils.to_number(raw) or 0
  local water_shortage
  local water_leakage
  local frost
  local fail_safe

  if is_duo_device(device) then
    -- Hydro DUO / SWV-ZF2 uses channel-specific shortage/fail-safe bits in the
    -- current Zigbee2MQTT public surface. The existing SmartThings capability is
    -- shared, so aggregate both channels into the common shortage/fail-safe rows.
    water_shortage = (n & (utils.DUO_ABNORMAL_WATER_SHORTAGE_CH1 | utils.DUO_ABNORMAL_WATER_SHORTAGE_CH2)) ~= 0
    water_leakage = (n & utils.DUO_ABNORMAL_WATER_LEAKAGE) ~= 0
    frost = (n & (utils.DUO_ABNORMAL_FROST_CH1 | utils.DUO_ABNORMAL_FROST_CH2)) ~= 0
    fail_safe = (n & (utils.DUO_ABNORMAL_FAIL_SAFE_CH1 | utils.DUO_ABNORMAL_FAIL_SAFE_CH2)) ~= 0
    local high_flow = (n & utils.DUO_ABNORMAL_HIGH_FLOW) ~= 0
    debug_log(device, "DUO abnormal-state raw=0x%02X shortage=%s leak=%s frost=%s failSafe=%s highFlow=%s", n, tostring(water_shortage), tostring(water_leakage), tostring(frost), tostring(fail_safe), tostring(high_flow))
  else
    water_shortage = (n & utils.ABNORMAL_WATER_SHORTAGE) ~= 0
    water_leakage = (n & utils.ABNORMAL_WATER_LEAKAGE) ~= 0
    frost = (n & utils.ABNORMAL_FROST_PROTECTION) ~= 0
    fail_safe = (n & utils.ABNORMAL_FAIL_SAFE) ~= 0
  end

  safe_emit(device, hydroValveAlerts, "waterShortage", water_shortage and "detected" or "clear")
  safe_emit(device, hydroValveAlerts, "waterLeakage", water_leakage and "detected" or "clear")
  safe_emit(device, hydroValveAlerts, "frostProtection", frost and "active" or "clear")
  safe_emit(device, hydroValveAlerts, "failSafe", fail_safe and "active" or "clear")

  -- Standard waterSensor is useful for automations; only actual leakage maps to "wet".
  if water_leakage then
    emit_capability_event(device, capabilities.waterSensor.water.wet(), "main")
  else
    emit_capability_event(device, capabilities.waterSensor.water.dry(), "main")
  end
end


local function manual_settings_from_elements(bytes)
  if type(bytes) ~= "table" or #bytes < 12 then return nil end
  local raw = {}
  for i = 1, 12 do raw[i] = (bytes[i] or 0) & 0xFF end
  local mode = raw[1]
  if mode < 0 or mode > 2 then return nil end
  local total_duration = (raw[2] << 8) | raw[3]
  local irrigation_duration = (raw[4] << 8) | raw[5]
  local interval_pause = (raw[6] << 8) | raw[7]
  local amount = (raw[9] << 8) | raw[10]
  local fail_safe = (raw[11] << 8) | raw[12]
  local duration = nil
  if mode ~= 1 and total_duration >= 0 and total_duration <= 719 then duration = total_duration end
  if mode ~= 1 and duration == nil then return nil end
  return {
    mode = mode,
    duration = duration,
    total_duration = total_duration,
    irrigation_duration = irrigation_duration,
    interval = interval_pause,
    interval_pause = interval_pause,
    amount_unit = raw[8],
    amount = amount,
    fail_safe = fail_safe <= 719 and fail_safe or nil,
    bytes = raw,
  }
end

local function manual_duration_from_elements(bytes)
  local settings = manual_settings_from_elements(bytes)
  return settings and settings.duration or nil
end

local function strip_array_header_if_present(bytes)
  if type(bytes) ~= "table" or #bytes < 3 then return bytes end
  if bytes[1] == data_types.Uint8.ID or bytes[1] == data_types.Array.ID then
    local count16 = (bytes[2] or 0) | ((bytes[3] or 0) << 8)
    if count16 > 0 and #bytes >= 3 + count16 then
      local elements = {}
      for i = 1, count16 do elements[i] = bytes[3 + i] & 0xFF end
      return elements
    end
    local count8 = bytes[2] or 0
    if count8 > 0 and #bytes >= 2 + count8 then
      local elements = {}
      for i = 1, count8 do elements[i] = bytes[2 + i] & 0xFF end
      return elements
    end
  end
  return bytes
end

process_manual_sync_readback = function(device, settings)
  local target = tonumber(device:get_field("manual_sync_target"))
  local phase = device:get_field("manual_sync_phase")
  if target == nil or phase == nil then return end

  local duration_matches = settings.mode == 0
    and settings.total_duration == target
    and settings.irrigation_duration == target
  local fail_safe_matches = is_lite_device(device) or settings.fail_safe == target
  if duration_matches and fail_safe_matches then
    clear_manual_sync(device, "verified", nil, target)
    debug_log(device, "0x501D synchronization verified target=%s failSafe=%s", tostring(target), tostring(settings.fail_safe))
    return
  end

  if phase == "verify_wait" then return end

  if phase == "verify" then
    clear_manual_sync(device, "failed", string.format("verification mismatch mode=%s total=%s irrigation=%s failSafe=%s expected=%s", tostring(settings.mode), tostring(settings.total_duration), tostring(settings.irrigation_duration), tostring(settings.fail_safe), tostring(target)))
    print("SONOFF Hydro ONE: device-side watering limit write was not verified; basic Open/Close is unaffected")
    return
  end

  if settings.mode ~= 0 or type(settings.bytes) ~= "table" or #settings.bytes < 12 then
    clear_manual_sync(device, "failed", "0x501D readback is not a complete duration-mode aggregate")
    print("SONOFF Hydro ONE: device-side watering limit could not be synchronized because the valve is not in duration mode; basic Open/Close is unaffected")
    return
  end

  -- Preserve the fresh 12-byte aggregate. Match Zigbee2MQTT's proven payload
  -- semantics by updating both duration fields. On full Hydro ONE / Hydro DUO,
  -- also update the separate fail-safe timeout to the
  -- same user-selected hard limit. Hydro ONE Lite exposes only duration in other
  -- integrations, so its remaining bytes stay untouched. Valve commands never
  -- depend on this transaction.
  local payload = {}
  for i = 1, 12 do payload[i] = settings.bytes[i] & 0xFF end
  payload[2] = (target >> 8) & 0xFF
  payload[3] = target & 0xFF
  payload[4] = (target >> 8) & 0xFF
  payload[5] = target & 0xFF
  if not is_lite_device(device) then
    payload[11] = (target >> 8) & 0xFF
    payload[12] = target & 0xFF
  end

  local ok_array, array_data = pcall(utils.build_explicit_uint8_array, payload)
  if not ok_array or array_data == nil then
    clear_manual_sync(device, "failed", "Array<Uint8> construction failed")
    return
  end
  local ok_message, message = pcall(utils.standard_write_attribute_data, device, utils.EWELINK_CLUSTER_ID, utils.ATTR_MANUAL_DEFAULT_SETTINGS, array_data)
  if not ok_message or message == nil then
    clear_manual_sync(device, "failed", "standard 0x501D write construction failed")
    return
  end
  local sent, send_err = pcall(send_zcl_to_component, device, "main", message)
  if not sent then
    clear_manual_sync(device, "failed", "0x501D send failed: " .. tostring(send_err))
    return
  end

  device:set_field("manual_sync_phase", "verify_wait")
  device:set_field("manual_default_write_mode", "alpha29-independent-duration-and-fail-safe")
  debug_log(device, "optional 0x501D write queued target=%s payload=%s", tostring(target), bytes_to_hex(payload))
  local delayed = false
  if device.thread and device.thread.call_with_delay then
    delayed = pcall(function()
      device.thread:call_with_delay(2, function()
        if device:get_field("manual_sync_phase") == "verify_wait" and tonumber(device:get_field("manual_sync_target")) == target then
          device:set_field("manual_sync_phase", "verify")
          read_private_attribute(device, utils.ATTR_MANUAL_DEFAULT_SETTINGS, "main")
        end
      end)
    end)
  end
  if not delayed then
    device:set_field("manual_sync_phase", "verify")
    read_private_attribute(device, utils.ATTR_MANUAL_DEFAULT_SETTINGS, "main")
  end
end

local function store_manual_settings(device, settings, allow_sync)
  if settings == nil then return false end
  device:set_field("manual_default_duration", settings.duration)
  device:set_field("manual_default_total_duration", settings.total_duration)
  device:set_field("manual_default_irrigation_duration", settings.irrigation_duration)
  device:set_field("manual_default_interval", settings.interval_pause)
  device:set_field("manual_default_fail_safe", settings.fail_safe)
  device:set_field("manual_default_settings", settings)
  if allow_sync == true then process_manual_sync_readback(device, settings) end
  return true
end

local function parse_manual_default_settings(device, decoded_value, allow_sync)
  local bytes = strip_array_header_if_present(utils.array_to_bytes(decoded_value))
  local settings = manual_settings_from_elements(bytes)
  if store_manual_settings(device, settings, allow_sync) then
    if settings.fail_safe ~= nil and settings.fail_safe > 0 and settings.duration ~= nil and settings.fail_safe < settings.duration then
      print(string.format("SONOFF Hydro ONE: 0x501D duration=%s min but fail-safe=%s min; firmware may close earlier", tostring(settings.duration), tostring(settings.fail_safe)))
    end
    debug_log(device, "manual_default_settings 0x501D mode=%s total=%s irrigation=%s pause=%s unit=%s amount=%s failSafe=%s bytes=%s", tostring(settings.mode), tostring(settings.total_duration), tostring(settings.irrigation_duration), tostring(settings.interval_pause), tostring(settings.amount_unit), tostring(settings.amount), tostring(settings.fail_safe), bytes_to_hex(settings.bytes))
  else
    debug_log(device, "manual_default_settings 0x501D readback could not decode complete aggregate bytes=%s", bytes_to_hex(bytes))
  end
end

local function handle_private_attribute(driver, device, attr_id, decoded_value, endpoint, source_kind)
  if (attr_id == utils.ATTR_MANUAL_DEFAULT_SETTINGS or attr_id == utils.ATTR_VALVE_ALARM_SETTINGS or attr_id == utils.ATTR_UNIT_OF_WATER_FLOW)
    and not shared_private_endpoint_is_valid(device, endpoint, "private readback") then return end
  local component_id = is_duo_device(device) and endpoint_to_component(device, endpoint or 1) or "main"
  local raw = utils.to_number(decoded_value)
  debug_log(device, "0xFC11 attr 0x%04X decoded=%s", attr_id, tostring(raw or decoded_value))

  if attr_id == utils.ATTR_CHILD_LOCK then
    local state = utils.to_bool(decoded_value) and "locked" or "unlocked"
    device:set_field("child_lock_state", state)
    debug_log(device, "child lock readback: %s", state)
  elseif attr_id == utils.ATTR_REAL_TIME_IRRIGATION_DURATION then
    -- 0x5006 is documented by ZHA as byte-swapped, but real Hydro ONE tests
    -- showed both plausible raw values and byte-swapped values. Decode
    -- defensively and never emit impossible multi-hundred-million minute values.
    local duration, raw_u32, swapped_u32, mode = utils.decode_u32_adaptive(decoded_value, 10080, "raw")
    local unit = "min"
    if device.preferences and device.preferences.realTimeDurationUnit == "seconds" then
      unit = "s"
    end
    debug_log(device, "real-time duration raw=%s swapped=%s selected=%s mode=%s %s", tostring(raw_u32), tostring(swapped_u32), tostring(duration), tostring(mode), unit)
    safe_emit(device, irrigation_status_capability(device), "realTimeIrrigationDuration", duration, unit, component_id)
  elseif attr_id == utils.ATTR_REAL_TIME_IRRIGATION_VOLUME then
    local volume, raw_u32, swapped_u32, mode = utils.decode_u32_adaptive(decoded_value, 100000, "raw")
    debug_log(device, "real-time volume raw=%s swapped=%s selected=%s mode=%s L", tostring(raw_u32), tostring(swapped_u32), tostring(volume), tostring(mode))
    if not is_lite_device(device) then
      safe_emit(device, hydroIrrigationStatus, "realTimeIrrigationVolume", volume, "L", "main")
    end
  elseif attr_id == utils.ATTR_VALVE_ABNORMAL_STATE then
    parse_abnormal_state(device, decoded_value)
  elseif attr_id == utils.ATTR_VALVE_WORK_STATE then
    safe_emit(device, irrigation_status_capability(device), "valveWorkState", utils.to_bool(decoded_value) and "working" or "idle", nil, component_id)
  elseif attr_id == utils.ATTR_HOUR_IRRIGATION_DURATION then
    debug_log(device, "hour duration raw=%s min", tostring(raw))
    safe_emit(device, irrigation_status_capability(device), "hourIrrigationDuration", raw or 0, "min", component_id)
  elseif attr_id == utils.ATTR_HOUR_IRRIGATION_VOLUME then
    debug_log(device, "hour volume raw=%s L", tostring(raw))
    if not is_lite_device(device) then
      safe_emit(device, hydroIrrigationStatus, "hourIrrigationVolume", raw or 0, "L", "main")
    end
  elseif attr_id == utils.ATTR_MANUAL_DEFAULT_SETTINGS then
    parse_manual_default_settings(device, decoded_value, source_kind == "read_response")
  elseif attr_id == utils.ATTR_UNIT_OF_WATER_FLOW then
    local code = utils.to_number(decoded_value)
    local unit = code ~= nil and utils.WATER_FLOW_UNIT_BY_CODE[code] or nil
    if code ~= nil then device:set_field("water_flow_unit_code", code, { persist = true }) end
    device:set_field("water_flow_unit", unit, { persist = true })
    debug_log(device, "unitOfWaterFlow 0x5021 code=%s unit=%s", tostring(code), tostring(unit))
  elseif attr_id == utils.ATTR_VALVE_ALARM_SETTINGS then
    if not is_lite_device(device) then
      parse_alarm_settings(device, decoded_value)
    else
      debug_log(device, "ignoring valve_alarm_settings report on Lite model")
    end
  else
    debug_log(device, "unhandled private attr 0x%04X", attr_id)
  end
end
local function private_cluster_records_handler(driver, device, zb_rx, source_kind)
  if zb_rx == nil or zb_rx.body == nil or zb_rx.body.zcl_body == nil or zb_rx.body.zcl_body.attr_records == nil then
    return
  end
  for _, record in ipairs(zb_rx.body.zcl_body.attr_records) do
    local attr_id = record.attr_id and record.attr_id.value
    if attr_id ~= nil and record.data ~= nil then
      handle_private_attribute(driver, device, attr_id, record.data.value or record.data, get_rx_endpoint(zb_rx), source_kind)
    end
  end
end

local function private_cluster_report_handler(driver, device, zb_rx)
  private_cluster_records_handler(driver, device, zb_rx, "report")
end

local function private_cluster_read_response_handler(driver, device, zb_rx)
  private_cluster_records_handler(driver, device, zb_rx, "read_response")
end

local function private_default_response_handler(driver, device, zb_rx)
  local command_id = nil
  local status = nil
  if zb_rx and zb_rx.body and zb_rx.body.zcl_body then
    local body = zb_rx.body.zcl_body
    command_id = (body.cmd_id and body.cmd_id.value) or (body.cmd and body.cmd.value) or (body.command_id and body.command_id.value)
    status = (body.status and body.status.value) or (body.zcl_status and body.zcl_status.value)
  end
  if status ~= nil and status ~= 0x00 then
    print(string.format("SONOFF Hydro ONE: 0xFC11 default response command=0x%02X status=0x%02X", command_id or 0xFF, status))
  else
    debug_log(device, "0xFC11 default response command=0x%02X status=0x%02X", command_id or 0xFF, status or 0x00)
  end
end

local function private_write_attribute_response_handler(driver, device, zb_rx)
  local body = zb_rx and zb_rx.body and zb_rx.body.zcl_body
  if body == nil then
    print("SONOFF Hydro ONE: 0xFC11 write attribute response received without parsed body")
    return
  end

  if body.global_status and body.global_status.value ~= nil then
    local status = body.global_status.value
    if status == 0x00 then
      debug_log(device, "0xFC11 write attribute response global_status=0x%02X", status)
    else
      print(string.format("SONOFF Hydro ONE: 0xFC11 write attribute response global_status=0x%02X", status))
    end
    return
  end

  if body.attr_records ~= nil then
    for _, record in ipairs(body.attr_records) do
      local attr_id = record.attr_id and record.attr_id.value or 0xFFFF
      local status = record.status and record.status.value or 0xFF
      if status == 0x00 then
        debug_log(device, "0xFC11 write attribute response attr=0x%04X status=0x%02X", attr_id, status)
      else
        print(string.format("SONOFF Hydro ONE: 0xFC11 write attribute response attr=0x%04X status=0x%02X", attr_id, status))
      end
    end
    return
  end

  debug_log(device, "0xFC11 write attribute response received")
end

local function add_string_bytes(out, s)
  if type(s) ~= "string" then return end
  for i = 1, #s do
    table.insert(out, string.byte(s, i) & 0xFF)
  end
end

local function add_table_bytes(out, t, depth)
  if type(t) ~= "table" or depth > 4 then return end

  if type(t.value) == "number" then
    table.insert(out, t.value & 0xFF)
    return
  end
  if type(t.data) == "number" then
    table.insert(out, t.data & 0xFF)
    return
  end
  if type(t.body_bytes) == "string" then
    add_string_bytes(out, t.body_bytes)
    return
  end
  if type(t.value) == "string" then
    add_string_bytes(out, t.value)
    return
  end
  if type(t.data) == "string" then
    add_string_bytes(out, t.data)
    return
  end
  if type(t.bytes) == "table" then
    add_table_bytes(out, t.bytes, depth + 1)
    return
  end

  for _, v in ipairs(t) do
    if type(v) == "number" then
      table.insert(out, v & 0xFF)
    elseif type(v) == "string" then
      add_string_bytes(out, v)
    elseif type(v) == "table" then
      add_table_bytes(out, v, depth + 1)
    end
  end
end

local function generic_body_to_bytes(zb_rx)
  local out = {}
  if zb_rx == nil or zb_rx.body == nil then return out end

  -- Depending on the Edge runtime, an unparsable ZCL body may be represented as
  -- body.value, body.data, body.body_bytes, or a small GenericBody table. Try the
  -- common shapes first and keep this intentionally defensive for beta testing.
  add_table_bytes(out, zb_rx.body, 0)

  if #out == 0 and zb_rx.body.zcl_body ~= nil then
    add_table_bytes(out, zb_rx.body.zcl_body, 0)
  end

  return out
end

local function parse_generic_array_payload(payload)
  -- SONOFF/eWeLink private cluster 0xFC11 reports several custom attributes as
  -- ZCL Array (0x48), but the payload is not a standard ZCL array.  The device
  -- uses a one-byte element count:
  --   element type, count, elements...
  -- Some tools/parsers expect the standard uint16 count and therefore shift the
  -- payload by one byte. Prefer the eWeLink one-byte format here, and only fall
  -- back to standard ZCL array parsing if the short format is not plausible.
  if payload == nil or #payload < 3 then return nil end

  local count8 = payload[2] or 0
  if count8 > 0 and #payload >= 2 + count8 then
    local bytes = {}
    for i = 1, count8 do
      bytes[i] = payload[2 + i] & 0xFF
    end
    return bytes
  end

  if #payload < 4 then return nil end
  local count16 = (payload[2] or 0) | ((payload[3] or 0) << 8)
  if count16 <= 0 or #payload < 3 + count16 then return nil end
  local bytes = {}
  for i = 1, count16 do
    bytes[i] = payload[3 + i] & 0xFF
  end
  return bytes
end

local function get_rx_cluster_id(zb_rx)
  local candidates = {
    zb_rx and zb_rx.address_header and zb_rx.address_header.cluster,
    zb_rx and zb_rx.address_header and zb_rx.address_header.cluster_id,
    zb_rx and zb_rx.cluster,
    zb_rx and zb_rx.cluster_id,
  }
  for _, c in ipairs(candidates) do
    if type(c) == "number" then return c end
    if type(c) == "table" and type(c.value) == "number" then return c.value end
  end
  return nil
end

local function handle_generic_private_body(driver, device, zb_rx)
  local cluster_id = get_rx_cluster_id(zb_rx)
  if cluster_id ~= nil and cluster_id ~= utils.EWELINK_CLUSTER_ID then return end

  local bytes = generic_body_to_bytes(zb_rx)
  if #bytes == 0 then
    print("SONOFF Hydro ONE: 0xFC11 generic body received but raw bytes could not be extracted")
    return
  end

  local frame_ctrl = bytes[1] or 0
  local offset = 2
  local mfg_code = nil
  if (frame_ctrl & 0x04) ~= 0 then
    mfg_code = (bytes[2] or 0) | ((bytes[3] or 0) << 8)
    offset = offset + 2 -- manufacturer code, little endian
  end

  -- If the runtime did not expose the cluster ID, only handle unmistakable
  -- SONOFF manufacturer-specific frames so the fallback stays quiet for other clusters.
  if cluster_id == nil and mfg_code ~= utils.SONOFF_MFG_CODE then return end

  debug_log(device, "0xFC11 generic body bytes: %s", bytes_to_hex(bytes))
  local seqno = bytes[offset] or 0
  local cmd = bytes[offset + 1]
  local pos = offset + 2

  -- Read Attributes Response, global command 0x01.
  if cmd == zcl_global_commands.ReadAttributeResponse.ID then
    while pos + 2 <= #bytes do
      local attr_id = (bytes[pos] or 0) | ((bytes[pos + 1] or 0) << 8)
      local status = bytes[pos + 2]
      pos = pos + 3
      if status ~= 0x00 then
        print(string.format("SONOFF Hydro ONE: 0xFC11 generic read response attr=0x%04X status=0x%02X", attr_id, status or 0xFF))
      else
        local data_type = bytes[pos]
        pos = pos + 1
        if attr_id == utils.ATTR_VALVE_ALARM_SETTINGS and data_type == data_types.Array.ID then
          local payload = {}
          for i = pos, #bytes do table.insert(payload, bytes[i]) end
          local settings_bytes = parse_generic_array_payload(payload)
          if settings_bytes ~= nil and #settings_bytes >= 4 then
            debug_log(device, "parsed generic valve_alarm_settings 0x5020 bytes: %s", bytes_to_hex(settings_bytes))
            if not is_lite_device(device) then
              parse_alarm_settings(device, settings_bytes)
            else
              debug_log(device, "ignoring generic valve_alarm_settings report on Lite model")
            end
            return
          end
          print("SONOFF Hydro ONE: failed to parse generic valve_alarm_settings 0x5020 payload: " .. bytes_to_hex(payload))
          return
        elseif attr_id == utils.ATTR_UNIT_OF_WATER_FLOW and data_type == data_types.Uint8.ID then
          local value = bytes[pos]
          if value ~= nil then handle_private_attribute(driver, device, attr_id, value, get_rx_endpoint(zb_rx)) end
          return
        elseif attr_id == utils.ATTR_MANUAL_DEFAULT_SETTINGS and data_type == data_types.Array.ID then
          local payload = {}
          for k = pos, #bytes do table.insert(payload, bytes[k]) end
          local settings_bytes = parse_generic_array_payload(payload)
          if settings_bytes ~= nil then
            local settings = manual_settings_from_elements(settings_bytes)
            if store_manual_settings(device, settings, true) then
              debug_log(device, "parsed generic manual_default_settings 0x501D bytes=%s", bytes_to_hex(settings_bytes))
            else
              debug_log(device, "generic manual_default_settings 0x501D payload was incomplete: %s", bytes_to_hex(settings_bytes))
            end
            return
          end
          print("SONOFF Hydro ONE: failed to parse generic manual_default_settings 0x501D payload: " .. bytes_to_hex(payload))
          return
        else
          print(string.format("SONOFF Hydro ONE: unhandled 0xFC11 generic read response attr=0x%04X type=0x%02X seq=0x%02X", attr_id, data_type or 0xFF, seqno))
          return
        end
      end
    end
    return
  end

  -- Write Attributes Response, global command 0x04. This is here mainly so the
  -- tester gets a useful status if Edge cannot parse the response after 0x5020 writes.
  if cmd == zcl_global_commands.WriteAttributeResponse.ID then
    if pos <= #bytes then
      local status = bytes[pos]
      if #bytes == pos then
        if status == 0x00 then
          debug_log(device, "0xFC11 generic write attribute response global_status=0x%02X", status)
        else
          print(string.format("SONOFF Hydro ONE: 0xFC11 generic write attribute response global_status=0x%02X", status or 0xFF))
        end
      elseif pos + 2 <= #bytes then
        local attr_id = (bytes[pos + 1] or 0) | ((bytes[pos + 2] or 0) << 8)
        if status == 0x00 then
          debug_log(device, "0xFC11 generic write attribute response attr=0x%04X status=0x%02X", attr_id, status)
        else
          print(string.format("SONOFF Hydro ONE: 0xFC11 generic write attribute response attr=0x%04X status=0x%02X", attr_id, status or 0xFF))
        end
      end
    end
    return
  end
end

local function zigbee_fallback_handler(driver, device, zb_rx)
  local ok, err = pcall(handle_generic_private_body, driver, device, zb_rx)
  if not ok then
    print("SONOFF Hydro ONE: zigbee fallback handler failed: " .. tostring(err))
  end
end

local function refresh_handler(driver, device, command)
  debug_log(device, "refresh requested with driver version %s", DRIVER_VERSION)
  read_standard_attributes(device)
  if device.preferences and device.preferences.readPrivateOnRefresh == false then
    ensure_manual_duration_sync(device, "manual Refresh", true, true)
  else
    -- Arm synchronization first, then reuse the normal 0x501D Refresh read.
    ensure_manual_duration_sync(device, "manual Refresh", false, true)
    read_private_attributes(device)
  end
end


local function switch_on_handler(driver, device, command)
  send_on(device, get_command_component(command))
end

local function switch_off_handler(driver, device, command)
  send_off(device, get_command_component(command))
end

local function valve_open_handler(driver, device, command)
  send_on(device, get_command_component(command))
end

local function valve_close_handler(driver, device, command)
  send_off(device, get_command_component(command))
end

local function open_for_minutes_handler(driver, device, command)
  local minutes = utils.get_arg(command, "minutes", 1, 1)
  send_timed_open(device, minutes, get_command_component(command))
end

local function stop_timed_watering_handler(driver, device, command)
  send_off(device, get_command_component(command))
end

local function added_handler(driver, device)
  setup_component_mapping(device)
  for _, component_id in ipairs(duo_component_ids(device)) do
    set_timed_session_active(device, component_id, false)
    next_timed_session_token(device, component_id)
    set_timed_recovery_required(device, component_id, false)
    emit_capability_event(device, capabilities.switch.switch.off(), component_id)
    emit_capability_event(device, capabilities.valve.valve.closed(), component_id)
    safe_emit(device, hydroTimedWatering, "timedWatering", "idle", nil, component_id)
    safe_emit(device, hydroTimedWatering, "timedOpenMinutes", 0, "min", component_id)
  end

  local status_cap = irrigation_status_capability(device)
  for _, component_id in ipairs(duo_component_ids(device)) do
    safe_emit(device, status_cap, "valveWorkState", "idle", nil, component_id)
    safe_emit(device, status_cap, "realTimeIrrigationDuration", 0, "min", component_id)
    safe_emit(device, status_cap, "hourIrrigationDuration", 0, "min", component_id)
  end

  if not is_lite_device(device) then
    emit_capability_event(device, capabilities.waterSensor.water.dry(), "main")
    safe_emit(device, hydroIrrigationStatus, "realTimeIrrigationVolume", 0, "L", "main")
    safe_emit(device, hydroIrrigationStatus, "hourIrrigationVolume", 0, "L", "main")
    safe_emit(device, hydroValveAlerts, "waterShortage", "clear")
    safe_emit(device, hydroValveAlerts, "waterLeakage", "clear")
    safe_emit(device, hydroValveAlerts, "frostProtection", "clear")
    safe_emit(device, hydroValveAlerts, "failSafe", "clear")
  end
end
local function recover_interrupted_timed_sessions(device)
  for _, component_id in ipairs(duo_component_ids(device)) do
    next_timed_session_token(device, component_id)
    set_timed_session_active(device, component_id, false)
    if timed_recovery_required(device, component_id) then
      local ok, err = pcall(function()
        send_zcl_to_component(device, component_id, OnOff.server.commands.Off(device))
      end)
      if ok then
        set_timed_recovery_required(device, component_id, false)
        emit_valve_state(device, false, component_id)
        print(string.format("SONOFF Hydro ONE: recovered interrupted timed watering with standard Off on component %s", tostring(component_id)))
      else
        print("SONOFF Hydro ONE: timed-watering recovery Off failed: " .. tostring(err))
      end
    end
    set_timed_watering_state(device, "idle", component_id)
  end
end

local function init_handler(driver, device)
  setup_component_mapping(device)
  recover_interrupted_timed_sessions(device)
  device:set_field("driver_version", DRIVER_VERSION, { persist = true })
  local cached_firmware = device:get_field("firmware_version")
  if cached_firmware ~= nil then device:emit_event(capabilities.firmwareUpdate.currentVersion({ value = tostring(cached_firmware) })) end
  read_standard_attributes(device)
  ensure_manual_duration_sync(device, "driver initialization", true, false)
  local family = is_duo_device(device) and "SONOFF Hydro DUO" or (is_lite_device(device) and "SONOFF Hydro ONE Lite" or "SONOFF Hydro ONE")
  print(string.format("%s: driver version %s initialized", family, DRIVER_VERSION))
end

local function driver_switched_handler(driver, device)
  setup_component_mapping(device)
  recover_interrupted_timed_sessions(device)
  read_standard_attributes(device)
  ensure_manual_duration_sync(device, "driver switched", true, true)
end

local function pref_values_equal(a, b)
  local na = tonumber(a)
  local nb = tonumber(b)
  if na ~= nil and nb ~= nil then
    return na == nb
  end
  return tostring(a) == tostring(b)
end

local function preference_changed(device, args, name)
  if device.preferences == nil or device.preferences[name] == nil then
    return false
  end

  local old_prefs = args and args.old_st_store and args.old_st_store.preferences
  local old_value = old_prefs and old_prefs[name] or nil
  local current_value = device.preferences[name]

  if old_value == nil then
    -- On upgraded devices, newly introduced preference keys may not exist in
    -- the old store yet.  On some Edge/runtime paths the old preference store
    -- can also be absent entirely.  Do not write default values merely because
    -- the preference is new, but do write a non-default value selected by the
    -- tester/user. This is important for manualDuration: changing it from 10 to
    -- 60 must write 0x501D even if old_st_store.preferences is missing.
    local default_value = PREFERENCE_DEFAULTS[name]
    if default_value == nil then
      return false
    end
    return not pref_values_equal(current_value, default_value)
  end

  return not pref_values_equal(old_value, current_value)
end

local function info_changed_handler(driver, device, event, args)
  if device.preferences == nil then return end

  if preference_changed(device, args, "childLock") then
    write_child_lock(device, device.preferences.childLock == "locked")
  end

  if preference_changed(device, args, "manualDuration") then
    write_manual_default_duration(device, device.preferences.manualDuration)
  end

  -- Hydro ONE Lite has no 0x5020 alarm/auto-close settings in this first support build.
  if is_lite_device(device) then
    return
  end

  local updates = {}
  if preference_changed(device, args, "shortageAlarm") then
    table.insert(updates, { kind = "bit", bit = utils.ALARM_WATER_SHORTAGE, enabled = device.preferences.shortageAlarm == "enabled" })
  end
  if preference_changed(device, args, "leakAlarm") then
    table.insert(updates, { kind = "bit", bit = utils.ALARM_WATER_LEAK, enabled = device.preferences.leakAlarm == "enabled" })
  end
  -- Hydro DUO public mappings currently expose only shortage/leak alarm enables,
  -- shortage auto-close, and the two alarm durations.  Do not write the older
  -- single-channel frost/leak-auto-close fields on DUO until real hardware logs
  -- confirm that the same 0x5020 bits are safe there as well.
  if not is_duo_device(device) and preference_changed(device, args, "frostAlarm") then
    table.insert(updates, { kind = "bit", bit = utils.ALARM_FROST_PROTECTION, enabled = device.preferences.frostAlarm == "enabled" })
  end
  if preference_changed(device, args, "shortageAutoClose") then
    table.insert(updates, { kind = "bit", bit = utils.ALARM_WATER_SHORTAGE_AUTO_CLOSE, enabled = device.preferences.shortageAutoClose == "enabled" })
  end
  if not is_duo_device(device) and preference_changed(device, args, "leakAutoClose") then
    table.insert(updates, { kind = "bit", bit = utils.ALARM_WATER_LEAK_AUTO_CLOSE, enabled = device.preferences.leakAutoClose == "enabled" })
  end
  if preference_changed(device, args, "shortageDuration") then
    table.insert(updates, { kind = "duration", field = "water_shortage_duration", minutes = device.preferences.shortageDuration, min_value = 1, max_value = 10, default_value = 1 })
  end
  if preference_changed(device, args, "leakDuration") then
    table.insert(updates, { kind = "duration", field = "water_leak_duration", minutes = device.preferences.leakDuration, min_value = 1, max_value = 3, default_value = 1 })
  end
  if not is_duo_device(device) and preference_changed(device, args, "frostThreshold") then
    table.insert(updates, { kind = "frost", degrees_c = device.preferences.frostThreshold })
  end

  apply_alarm_updates(device, updates, "preference change")
end

local function do_configure_handler(driver, device)
  device:configure()

  -- Bind/report only the very small standard set. This is a sleepy battery valve; avoid chatty polling.
  setup_component_mapping(device)
  local ok, err = pcall(function()
    send_zcl_to_component(device, "main", device_management.build_bind_request(device, OnOff.ID, driver.environment_info.hub_zigbee_eui))
    send_zcl_to_component(device, "main", OnOff.attributes.OnOff:configure_reporting(device, 0, 600))
    if is_duo_device(device) then
      send_zcl_to_component(device, "channel2", device_management.build_bind_request(device, OnOff.ID, driver.environment_info.hub_zigbee_eui))
      send_zcl_to_component(device, "channel2", OnOff.attributes.OnOff:configure_reporting(device, 0, 600))
    end
    send_zcl_to_component(device, "main", PowerConfiguration.attributes.BatteryPercentageRemaining:configure_reporting(device, 30, 21600, 2))
    send_zcl_to_component(device, "main", device_management.build_bind_request(device, PollControl.ID, driver.environment_info.hub_zigbee_eui))
  end)
  if not ok then
    print("SONOFF Hydro ONE: standard configure failed/partially failed: " .. tostring(err))
  end

  -- Do not configure reporting for the SONOFF private cluster in the first public test build.
  -- Zigbee2MQTT treats these fields as STATE_GET and only binds/reads standard OnOff;
  -- private configure-reporting attempts add noise and may wake the battery valve unnecessarily.
  read_standard_attributes(device)
  read_private_attributes(device)

  device:emit_event(capabilities.healthCheck.checkInterval(2 * 60 * 60 + 60, { visibility = { displayed = false } }))
end

local driver_template = {
  -- SmartThings has deprecated the legacy Zigbee monitored-attributes health check.
  -- The driver still emits a healthCheck interval; this disables the old template-level checker.
  health_check = false,
  supported_capabilities = {
    capabilities.valve,
    capabilities.switch,
    capabilities.battery,
    capabilities.waterSensor,
    capabilities.refresh,
    capabilities.healthCheck,
    capabilities.firmwareUpdate,
    hydroTimedWatering,
    hydroIrrigationStatus,
    hydroLiteIrrigationStatus,
    hydroValveAlerts,
  },
  lifecycle_handlers = {
    added = added_handler,
    init = init_handler,
    infoChanged = info_changed_handler,
    doConfigure = do_configure_handler,
    driverSwitched = driver_switched_handler,
  },
  capability_handlers = {
    [capabilities.switch.ID] = {
      [capabilities.switch.commands.on.NAME] = switch_on_handler,
      [capabilities.switch.commands.off.NAME] = switch_off_handler,
    },
    [capabilities.valve.ID] = {
      [capabilities.valve.commands.open.NAME] = valve_open_handler,
      [capabilities.valve.commands.close.NAME] = valve_close_handler,
    },
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = refresh_handler,
    },
    [hydroTimedWatering.ID] = {
      [hydroTimedWatering.commands.openForMinutes.NAME] = guarded("openForMinutes", open_for_minutes_handler),
      [hydroTimedWatering.commands.stop.NAME] = guarded("stopTimedWatering", stop_timed_watering_handler),
    },
  },
  zigbee_handlers = {
    attr = {
      [Basic.ID] = {
        [Basic.attributes.SWBuildID.ID] = firmware_version_attr_handler,
      },
      [OnOff.ID] = {
        [OnOff.attributes.OnOff.ID] = onoff_attr_handler,
      },
      [PowerConfiguration.ID] = {
        [PowerConfiguration.attributes.BatteryPercentageRemaining.ID] = battery_attr_handler,
      },
    },
    global = {
      [utils.EWELINK_CLUSTER_ID] = {
        [zcl_global_commands.ReportAttribute.ID] = private_cluster_report_handler,
        [zcl_global_commands.ReadAttributeResponse.ID] = private_cluster_read_response_handler,
        [zcl_global_commands.WriteAttributeResponse.ID] = private_write_attribute_response_handler,
        [zcl_global_commands.DefaultResponse.ID] = private_default_response_handler,
      },
    },
    fallback = zigbee_fallback_handler,
  },
}

local driver = ZigbeeDriver("sonoff-hydro-one", driver_template)
driver:run()
