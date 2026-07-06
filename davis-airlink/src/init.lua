local Driver = require "st.driver"
local capabilities = require "st.capabilities"
local log = require "log"

local api = require "airlink.api"
local constants = require "airlink.constants"
local discovery = require "airlink.discovery"
local health = require "airlink.health"
local util = require "airlink.util"

local driver_template = {}

local function get_effective_host(device)
  return util.get_host_override(device) or device:get_field(constants.FIELD_HOST)
end

local function get_effective_port(device)
  return tonumber(device:get_field(constants.FIELD_PORT)) or constants.DEFAULT_PORT
end

local function emit_if_present(device, capability_event_builder, value, unit)
  if value == nil then return false end
  if unit ~= nil then
    device:emit_event(capability_event_builder({ value = value, unit = unit }))
  else
    device:emit_event(capability_event_builder(value))
  end
  return true
end

local function emit_sensor_events(device, data)
  local condition = data and data.condition
  if not condition then return end

  local temp_c = util.round(util.f_to_c(condition.temp_f), 1)
  local humidity = util.round(condition.humidity, 1)
  local pm1 = util.round_int_non_negative(condition.pm1)
  local pm25 = util.round_int_non_negative(condition.pm25)
  local pm10 = util.round_int_non_negative(condition.pm10)
  local health_basis = util.get_health_basis(device)
  local health_values = health.calculate(condition, health_basis)

  emit_if_present(device, capabilities.temperatureMeasurement.temperature, temp_c, "C")
  emit_if_present(device, capabilities.relativeHumidityMeasurement.humidity, humidity, "%")
  emit_if_present(device, capabilities.veryFineDustSensor.veryFineDustLevel, pm1, constants.PM_UNIT)
  emit_if_present(device, capabilities.fineDustSensor.fineDustLevel, pm25, constants.PM_UNIT)
  emit_if_present(device, capabilities.dustSensor.dustLevel, pm10, constants.PM_UNIT)

  emit_if_present(device, capabilities.veryFineDustHealthConcern.veryFineDustHealthConcern, health_values.very_fine)
  emit_if_present(device, capabilities.fineDustHealthConcern.fineDustHealthConcern, health_values.fine)
  emit_if_present(device, capabilities.dustHealthConcern.dustHealthConcern, health_values.dust)
  emit_if_present(device, capabilities.airQualityHealthConcern.airQualityHealthConcern, health_values.overall)

  if util.get_debug_logging(device) then
    log.info(string.format(
      "AirLink poll ok did=%s name=%s dst=%s temp=%sC hum=%s%% pm1=%s pm25=%s pm10=%s raw_pm1=%s raw_pm25=%s raw_pm10=%s healthBasis=%s healthPm25=%s healthPm10=%s health=%s/%s/%s overall=%s pct1h=%s pct3h=%s pctNowcast=%s pct24h=%s ts=%s last=%s",
      tostring(data.did),
      tostring(data.name),
      tostring(condition.data_structure_type),
      tostring(temp_c),
      tostring(humidity),
      tostring(pm1),
      tostring(pm25),
      tostring(pm10),
      tostring(condition.pm1),
      tostring(condition.pm25),
      tostring(condition.pm10),
      tostring(health_values.basis),
      tostring(health_values.pm25_for_health),
      tostring(health_values.pm10_for_health),
      tostring(health_values.very_fine),
      tostring(health_values.fine),
      tostring(health_values.dust),
      tostring(health_values.overall),
      tostring(condition.pct_1h),
      tostring(condition.pct_3h),
      tostring(condition.pct_nowcast),
      tostring(condition.pct_24h),
      tostring(data.ts),
      tostring(condition.last_report_time)
    ))
  end
end

local function save_success_fields(device, host, port, data)
  discovery.save_network_fields(device, host, port, data.did, data.name)
  device:set_field(constants.FIELD_FAILURE_COUNT, 0)
  device:set_field(constants.FIELD_LAST_DATA, data)
end

local function mark_failure(driver, device, err)
  local failures = tonumber(device:get_field(constants.FIELD_FAILURE_COUNT)) or 0
  failures = failures + 1
  device:set_field(constants.FIELD_FAILURE_COUNT, failures)

  log.warn(string.format("AirLink poll failed device=%s failures=%d err=%s", tostring(device.label or device.device_network_id), failures, tostring(err)))

  if failures == constants.OFFLINE_AFTER_FAILURES and not util.get_host_override(device) then
    local ok, rediscover_err = discovery.rediscover_existing_device(driver, device)
    if ok then
      log.info("AirLink rediscovery after repeated poll failure succeeded; next poll will use the updated address")
    else
      log.warn("AirLink rediscovery after repeated poll failure failed: " .. tostring(rediscover_err))
    end
  end

  if failures >= constants.OFFLINE_AFTER_FAILURES then
    pcall(function() device:offline() end)
  end
end

local function poll_device(driver, device, source)
  if device:get_field(constants.FIELD_POLL_IN_PROGRESS) then
    log.warn("Skipping AirLink poll because a previous request is still in progress")
    return
  end

  local host = get_effective_host(device)
  local port = get_effective_port(device)

  if not util.is_non_empty_string(host) then
    log.warn("AirLink has no known host yet; attempting rediscovery")
    local ok, err = discovery.rediscover_existing_device(driver, device)
    if not ok then
      mark_failure(driver, device, "no known host and rediscovery failed: " .. tostring(err))
      return
    end
    host = get_effective_host(device)
    port = get_effective_port(device)
  end

  device:set_field(constants.FIELD_POLL_IN_PROGRESS, true)
  device:set_field(constants.FIELD_LAST_POLL_SOURCE, source or "unknown")

  local data, err = api.fetch_current_conditions(host, port)

  device:set_field(constants.FIELD_POLL_IN_PROGRESS, false)

  if not data then
    mark_failure(driver, device, err)
    return
  end

  local expected_did = device:get_field(constants.FIELD_DID) or util.did_from_dni(device.device_network_id)
  if expected_did and tostring(data.did) ~= tostring(expected_did) then
    mark_failure(driver, device, string.format("DID mismatch expected=%s got=%s host=%s", tostring(expected_did), tostring(data.did), tostring(host)))
    return
  end

  save_success_fields(device, host, port, data)
  pcall(function() device:online() end)
  emit_sensor_events(device, data)
end

local function cancel_poll_timer(device)
  local timer = device:get_field(constants.FIELD_POLL_TIMER)
  if timer ~= nil then
    pcall(function() device.thread:cancel_timer(timer) end)
    pcall(function() device.driver:cancel_timer(timer) end)
  end
  device:set_field(constants.FIELD_POLL_TIMER, nil)
end

local function schedule_poll(driver, device, initial_delay)
  cancel_poll_timer(device)

  local interval = util.get_poll_interval(device)
  local delay = tonumber(initial_delay) or interval

  local timer = device.thread:call_with_delay(delay, function()
    device:set_field(constants.FIELD_POLL_TIMER, nil)

    local ok, err = pcall(function()
      poll_device(driver, device, "scheduled")
    end)

    if not ok then
      device:set_field(constants.FIELD_POLL_IN_PROGRESS, false)
      log.error("Unexpected AirLink polling error: " .. tostring(err))
      mark_failure(driver, device, "unexpected polling error: " .. tostring(err))
    end

    schedule_poll(driver, device, util.get_poll_interval(device))
  end, "Davis AirLink scheduled poll")

  device:set_field(constants.FIELD_POLL_TIMER, timer)
  if util.get_debug_logging(device) then
    log.info(string.format("Scheduled AirLink poll in %s seconds for %s", tostring(delay), tostring(device.label or device.device_network_id)))
  end
end

local function device_added(driver, device)
  log.info("Davis AirLink device added: " .. tostring(device.device_network_id))
  device:set_field(constants.FIELD_FAILURE_COUNT, 0)
  discovery.apply_pending_fields(device)
end

local function device_init(driver, device)
  log.info("Davis AirLink device init: " .. tostring(device.device_network_id))

  local did = util.did_from_dni(device.device_network_id)
  if did and not device:get_field(constants.FIELD_DID) then
    device:set_field(constants.FIELD_DID, did, { persist = true })
  end

  discovery.apply_pending_fields(device)

  -- Delay the first poll slightly so newly-created LAN devices can finish initialization.
  schedule_poll(driver, device, 2)
end

local function device_removed(_, device)
  log.info("Davis AirLink device removed: " .. tostring(device.device_network_id))
  cancel_poll_timer(device)
end

local function info_changed(driver, device, event, args)
  log.info("Davis AirLink preferences/info changed for " .. tostring(device.device_network_id))

  if args and args.old_st_store and args.old_st_store.preferences then
    local old_prefs = args.old_st_store.preferences
    local new_poll = device.preferences and device.preferences.pollInterval
    local new_host = device.preferences and device.preferences.hostOverride
    local new_debug = device.preferences and device.preferences.debugLogging
    local new_health_basis = device.preferences and device.preferences.healthBasis
    if tostring(old_prefs.pollInterval) ~= tostring(new_poll) then
      log.info(string.format("AirLink poll interval changed from %s to %s", tostring(old_prefs.pollInterval), tostring(new_poll)))
    end
    if tostring(old_prefs.hostOverride) ~= tostring(new_host) then
      log.info(string.format("AirLink host override changed from %s to %s", tostring(old_prefs.hostOverride), tostring(new_host)))
    end
    if tostring(old_prefs.debugLogging) ~= tostring(new_debug) then
      log.info(string.format("AirLink debug logging changed from %s to %s", tostring(old_prefs.debugLogging), tostring(new_debug)))
    end
    if tostring(old_prefs.healthBasis) ~= tostring(new_health_basis) then
      log.info(string.format("AirLink health basis changed from %s to %s", tostring(old_prefs.healthBasis), tostring(new_health_basis)))
    end
  end

  schedule_poll(driver, device, 1)
end

local function refresh_handler(driver, device, command)
  log.info("Manual AirLink refresh requested for " .. tostring(device.label or device.device_network_id))
  local ok, err = pcall(function()
    poll_device(driver, device, "refresh")
  end)
  if not ok then
    device:set_field(constants.FIELD_POLL_IN_PROGRESS, false)
    log.error("Unexpected AirLink refresh error: " .. tostring(err))
    mark_failure(driver, device, "unexpected refresh error: " .. tostring(err))
  end
end

driver_template.discovery = discovery.handle_discovery

driver_template.lifecycle_handlers = {
  added = device_added,
  init = device_init,
  removed = device_removed,
  infoChanged = info_changed,
}

driver_template.capability_handlers = {
  [capabilities.refresh.ID] = {
    [capabilities.refresh.commands.refresh.NAME] = refresh_handler,
  },
}

local davis_airlink_driver = Driver(constants.DRIVER_NAME, driver_template)
log.info(string.format("Starting %s driver v%s", constants.DRIVER_NAME, constants.DRIVER_VERSION))
davis_airlink_driver:run()
