-- Copyright 2026
-- Minimal SmartThings Edge driver for Aqara Curtain Driver E1 (lumi.curtain.agl001)

local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"
local clusters = require "st.zigbee.zcl.clusters"
local cluster_base = require "st.zigbee.cluster_base"
local data_types = require "st.zigbee.data_types"
local FrameCtrl = require "st.zigbee.zcl.frame_ctrl"
local utils = require "st.utils"

local Basic = clusters.Basic
local PowerConfiguration = clusters.PowerConfiguration
local WindowCovering = clusters.WindowCovering
local Groups = clusters.Groups

local initializedStateWithGuide = capabilities["stse.initializedStateWithGuide"]
local hookLockState = capabilities["stse.hookLockState"]
local chargingState = capabilities["stse.chargingState"]

local reverseCurtainDirection = "stse.reverseCurtainDirection"
local softTouch = "stse.softTouch"
local hookUnlockCommandName = "hookUnlock"
local hookLockCommandName = "hookLock"

local PRIVATE_CLUSTER_ID = 0xFCC0
local MFG_CODE = 0x115F
local PRIVATE_CURTAIN_MANUAL_ATTRIBUTE_ID = 0x0401
local PRIVATE_CURTAIN_RANGE_FLAG_ATTRIBUTE_ID = 0x0402
local PRIVATE_CURTAIN_STATUS_ATTRIBUTE_ID = 0x0421
local PRIVATE_CURTAIN_LOCKING_SETTING_ATTRIBUTE_ID = 0x0427
local PRIVATE_CURTAIN_LOCKING_STATUS_ATTRIBUTE_ID = 0x0428
local PRIVATE_CURTAIN_LIGHT_LEVEL_ATTRIBUTE_ID = 0x0429

local SHADE_STATE_CLOSE = 0
local SHADE_STATE_OPEN = 1
local SHADE_STATE_STOP = 2

local BATTERY_CONFIGURATIONS = {
  {
    cluster = PowerConfiguration.ID,
    attribute = PowerConfiguration.attributes.BatteryPercentageRemaining.ID,
    minimum_interval = 30,
    maximum_interval = 3600,
    data_type = PowerConfiguration.attributes.BatteryPercentageRemaining.base_type,
    reportable_change = 1,
  },
}

local function emit_if_latest_state_missing(device, component_id, capability, attribute_name, event)
  local latest = device:get_latest_state(component_id, capability.ID, attribute_name)
  if latest == nil then
    if component_id == "main" then
      device:emit_event(event)
    else
      device:emit_component_event(device.profile.components[component_id], event)
    end
  end
end

local function custom_write_attribute(device, cluster_id, attribute_id, data_type, value, mfg_code)
  local data = data_types.validate_or_build_type(value, data_type)
  local message = cluster_base.write_attribute(device, data_types.ClusterId(cluster_id), attribute_id, data)
  if mfg_code ~= nil then
    message.body.zcl_header.frame_ctrl:set_mfg_specific()
    message.body.zcl_header.mfg_code = data_types.validate_or_build_type(mfg_code, data_types.Uint16, "mfg_code")
  else
    message.body.zcl_header.frame_ctrl = FrameCtrl(0x10)
  end
  return message
end

local function emit_shade_level_event(device, raw_level)
  local level = math.max(0, math.min(100, utils.round(tonumber(raw_level) or 0)))
  device:emit_event(capabilities.windowShadeLevel.shadeLevel(level))
  return level
end

local function emit_shade_event_from_level(device, level)
  if level >= 100 then
    device:emit_event(capabilities.windowShade.windowShade.open())
  elseif level == 0 then
    device:emit_event(capabilities.windowShade.windowShade.closed())
  else
    device:emit_event(capabilities.windowShade.windowShade.partially_open())
  end
end

local function emit_illuminance_event(device, lux, zb_rx)
  lux = math.max(0, math.floor(tonumber(lux) or 0))
  if zb_rx and zb_rx.address_header and zb_rx.address_header.src_endpoint then
    device:emit_event_for_endpoint(
      zb_rx.address_header.src_endpoint.value,
      capabilities.illuminanceMeasurement.illuminance(lux)
    )
  else
    device:emit_event(capabilities.illuminanceMeasurement.illuminance(lux))
  end
end

local function window_covering_position_handler(driver, device, value, zb_rx)
  local level = emit_shade_level_event(device, value.value)
  emit_shade_event_from_level(device, level)
end

local function curtain_light_level_report_handler(driver, device, value, zb_rx)
  local raw = tonumber(value.value) or 0
  local lux = raw <= 0 and 0 or (raw * 50)
  emit_illuminance_event(device, lux, zb_rx)
end

local function shade_state_report_handler(driver, device, value, zb_rx)
  local state = value.value
  if state == SHADE_STATE_STOP then
    device:send(WindowCovering.attributes.CurrentPositionLiftPercentage:read(device))
  elseif state == SHADE_STATE_OPEN then
    device:emit_event(capabilities.windowShade.windowShade.opening())
  elseif state == SHADE_STATE_CLOSE then
    device:emit_event(capabilities.windowShade.windowShade.closing())
  end
end

local function curtain_range_report_handler(driver, device, value, zb_rx)
  if value.value == true then
    device:emit_event(initializedStateWithGuide.initializedStateWithGuide.initialized())
  else
    device:emit_event(initializedStateWithGuide.initializedStateWithGuide.notInitialized())
  end
end

local function curtain_state_of_charge_report_handler(driver, device, value, zb_rx)
  if value.value == 3 then
    device:emit_event(chargingState.chargingState.stopped())
  elseif value.value == 4 then
    device:emit_event(chargingState.chargingState.charging())
  elseif value.value == 7 then
    device:emit_event(chargingState.chargingState.fullyCharged())
  end
end

local function battery_energy_status_handler(driver, device, value, zb_rx)
  device:emit_event(capabilities.battery.battery(math.floor(value.value / 2.0 + 0.5)))
end

local function window_locking_status_handler(driver, device, value, zb_rx)
  if value.value == 0 then
    device:emit_event(hookLockState.hookLockState.unlocked())
  elseif value.value == 1 then
    device:emit_event(hookLockState.hookLockState.locked())
  elseif value.value == 2 then
    device:emit_event(hookLockState.hookLockState.locking())
  elseif value.value == 3 then
    device:emit_event(hookLockState.hookLockState.unlocking())
  end
end

local function do_refresh(driver, device)
  device:send(cluster_base.read_manufacturer_specific_attribute(device, PRIVATE_CLUSTER_ID, PRIVATE_CURTAIN_RANGE_FLAG_ATTRIBUTE_ID, MFG_CODE))
  device:send(cluster_base.read_manufacturer_specific_attribute(device, PRIVATE_CLUSTER_ID, PRIVATE_CURTAIN_LOCKING_STATUS_ATTRIBUTE_ID, MFG_CODE))
  device:send(cluster_base.read_manufacturer_specific_attribute(device, PRIVATE_CLUSTER_ID, PRIVATE_CURTAIN_LIGHT_LEVEL_ATTRIBUTE_ID, MFG_CODE))
  device:send(WindowCovering.attributes.CurrentPositionLiftPercentage:read(device))
  device:send(PowerConfiguration.attributes.BatteryPercentageRemaining:read(device))
end

local function do_configure(driver, device)
  device:configure()
  device:send(Groups.server.commands.RemoveAllGroups(device))
  do_refresh(driver, device)
end

local function device_init(driver, device)
  for _, attribute in ipairs(BATTERY_CONFIGURATIONS) do
    device:add_configured_attribute(attribute)
  end
end

local function device_added(driver, device)
  device:emit_event(capabilities.windowShade.supportedWindowShadeCommands({ "open", "close", "pause" }, { visibility = { displayed = false } }))
  emit_if_latest_state_missing(device, "main", capabilities.windowShadeLevel, capabilities.windowShadeLevel.shadeLevel.NAME, capabilities.windowShadeLevel.shadeLevel(0))
  emit_if_latest_state_missing(device, "main", capabilities.windowShade, capabilities.windowShade.windowShade.NAME, capabilities.windowShade.windowShade.closed())
  emit_if_latest_state_missing(device, "main", capabilities.illuminanceMeasurement, capabilities.illuminanceMeasurement.illuminance.NAME, capabilities.illuminanceMeasurement.illuminance(0))
  device:emit_event(initializedStateWithGuide.initializedStateWithGuide.notInitialized())
  device:emit_event(hookLockState.hookLockState.unlocked())
  device:emit_event(chargingState.chargingState.stopped())
  device:emit_event(capabilities.battery.battery(100))
end

local function device_info_changed(driver, device, event, args)
  if device.preferences == nil then return end

  local reverseCurtainDirectionPrefValue = device.preferences[reverseCurtainDirection]
  local softTouchPrefValue = device.preferences[softTouch]
  local old_prefs = args.old_st_store and args.old_st_store.preferences or {}

  if reverseCurtainDirectionPrefValue ~= nil and reverseCurtainDirectionPrefValue ~= old_prefs[reverseCurtainDirection] then
    local raw_value = reverseCurtainDirectionPrefValue and 0x01 or 0x00
    device:send(custom_write_attribute(device, WindowCovering.ID, WindowCovering.attributes.Mode.ID, data_types.Bitmap8, raw_value, nil))
  end

  if softTouchPrefValue ~= nil and softTouchPrefValue ~= old_prefs[softTouch] then
    device:send(cluster_base.write_manufacturer_specific_attribute(device, PRIVATE_CLUSTER_ID, PRIVATE_CURTAIN_MANUAL_ATTRIBUTE_ID, MFG_CODE, data_types.Boolean, (not softTouchPrefValue)))
  end
end

local function window_shade_level_set_cmd(driver, device, command)
  local level = math.max(0, math.min(100, utils.round(command.args.shadeLevel or 0)))
  device:emit_event(capabilities.windowShadeLevel.shadeLevel(level))
  device:send_to_component(command.component, WindowCovering.server.commands.GoToLiftPercentage(device, level))
end

local function is_initialized(device)
  local state = device:get_latest_state("main", initializedStateWithGuide.ID, initializedStateWithGuide.initializedStateWithGuide.NAME)
  return state == initializedStateWithGuide.initializedStateWithGuide.initialized.NAME
end

local function window_shade_open_cmd(driver, device, command)
  if is_initialized(device) then
    device:send_to_component(command.component, WindowCovering.server.commands.UpOrOpen(device))
  end
end

local function window_shade_pause_cmd(driver, device, command)
  if is_initialized(device) then
    device:send_to_component(command.component, WindowCovering.server.commands.Stop(device))
  end
end

local function window_shade_close_cmd(driver, device, command)
  if is_initialized(device) then
    device:send_to_component(command.component, WindowCovering.server.commands.DownOrClose(device))
  end
end

local function hook_lock_cmd(driver, device, command)
  device:send(cluster_base.write_manufacturer_specific_attribute(device, PRIVATE_CLUSTER_ID, PRIVATE_CURTAIN_LOCKING_SETTING_ATTRIBUTE_ID, MFG_CODE, data_types.Uint8, 0x01))
end

local function hook_unlock_cmd(driver, device, command)
  device:send(cluster_base.write_manufacturer_specific_attribute(device, PRIVATE_CLUSTER_ID, PRIVATE_CURTAIN_LOCKING_SETTING_ATTRIBUTE_ID, MFG_CODE, data_types.Uint8, 0x00))
end

local driver_template = {
  supported_capabilities = {
    capabilities.windowShade,
    capabilities.windowShadeLevel,
    capabilities.battery,
    capabilities.illuminanceMeasurement,
    initializedStateWithGuide,
    hookLockState,
    chargingState,
    capabilities.refresh,
  },
  lifecycle_handlers = {
    init = device_init,
    added = device_added,
    doConfigure = do_configure,
    infoChanged = device_info_changed,
  },
  capability_handlers = {
    [capabilities.windowShade.ID] = {
      [capabilities.windowShade.commands.open.NAME] = window_shade_open_cmd,
      [capabilities.windowShade.commands.pause.NAME] = window_shade_pause_cmd,
      [capabilities.windowShade.commands.close.NAME] = window_shade_close_cmd,
    },
    [capabilities.windowShadeLevel.ID] = {
      [capabilities.windowShadeLevel.commands.setShadeLevel.NAME] = window_shade_level_set_cmd,
    },
    [hookLockState.ID] = {
      [hookLockCommandName] = hook_lock_cmd,
      [hookUnlockCommandName] = hook_unlock_cmd,
    },
    [capabilities.refresh.ID] = {
      [capabilities.refresh.commands.refresh.NAME] = do_refresh,
    },
  },
  zigbee_handlers = {
    attr = {
      [Basic.ID] = {
        [Basic.attributes.PowerSource.ID] = curtain_state_of_charge_report_handler,
      },
      [PowerConfiguration.ID] = {
        [PowerConfiguration.attributes.BatteryPercentageRemaining.ID] = battery_energy_status_handler,
      },
      [WindowCovering.ID] = {
        [WindowCovering.attributes.CurrentPositionLiftPercentage.ID] = window_covering_position_handler,
      },
      [PRIVATE_CLUSTER_ID] = {
        [PRIVATE_CURTAIN_RANGE_FLAG_ATTRIBUTE_ID] = curtain_range_report_handler,
        [PRIVATE_CURTAIN_STATUS_ATTRIBUTE_ID] = shade_state_report_handler,
        [PRIVATE_CURTAIN_LOCKING_STATUS_ATTRIBUTE_ID] = window_locking_status_handler,
        [PRIVATE_CURTAIN_LIGHT_LEVEL_ATTRIBUTE_ID] = curtain_light_level_report_handler,
      },
    },
  },
  health_check = false,
}

local driver = ZigbeeDriver("aqara_curtain_driver_e1", driver_template)
driver:run()
