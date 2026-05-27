local Driver = require "st.driver"
local capabilities = require "st.capabilities"
local log = require "log"
local cosock = require "cosock"
local TuyaClient = require "tuya.client"
local TuyaTcpScan = require "tuya.tcp_scan"

local DRIVER_NAME = "Tuya Air Purifier Local"
local DNI = "tuya-air-purifier-local"

local CAP_SWITCH = capabilities.switch
local CAP_REFRESH = capabilities.refresh
local CAP_AP_MODE = capabilities.airPurifierFanMode
local CAP_PM25 = capabilities.fineDustSensor
local CAP_AQ = capabilities.airQualityHealthConcern
local CAP_FILTER = capabilities.filterState
local CAP_DISPLAY_LIGHT = capabilities["oceancircle09600.airPurifierDisplayLight"]
local CAP_TIMER = capabilities["oceancircle09600.airPurifierTimer"]

local MODE_ST_TO_TUYA = {
  auto = "auto",
  high = "H",
  sleep = "sleep",
  off = "off",
}

local MODE_TUYA_TO_ST = {
  auto = "auto",
  H = "high",
  sleep = "sleep",
}

local AQ_TUYA_TO_ST = {
  great = "good",
  mild = "moderate",
  good = "slightlyUnhealthy",
  medium = "unhealthy",
  severe = "hazardous",
}

local LIGHT_TUYA_TO_CUSTOM = {
  Close = "off",
  Soft = "soft",
  Standard = "standard",
}

local LIGHT_CUSTOM_TO_TUYA = {
  off = "Close",
  soft = "Soft",
  standard = "Standard",
}

local TIMER_TUYA_TO_CUSTOM = {
  cancel = "off",
  ["2h"] = "twoHours",
  ["4h"] = "fourHours",
}

local TIMER_CUSTOM_TO_TUYA = {
  off = "cancel",
  twoHours = "2h",
  fourHours = "4h",
}

local function safe_tonumber(value, fallback)
  if value == nil then return fallback end
  local ok, number = pcall(tonumber, value)
  if ok and number ~= nil then return number end
  return fallback
end


local function auto_rediscovery_enabled(device)
  -- Default to enabled.  Older devices created before the preference existed may
  -- have nil here, which should still mean enabled.
  return device.preferences.autoRediscovery ~= false
end

local function get_manual_host(device)
  return device.preferences.host
end

local function get_runtime_host(device)
  if auto_rediscovery_enabled(device) then
    local discovered = device:get_field("runtime_host")
    if discovered and discovered ~= "" then return discovered end
  end
  return get_manual_host(device)
end

local function set_runtime_host(device, host, reason)
  if not host or host == "" then return false end
  local current = device:get_field("runtime_host")
  if current == host then return false end
  device:set_field("runtime_host", host, { persist = true })
  device:set_field("runtime_host_reason", reason or "rediscovery", { persist = true })
  device:set_field("runtime_host_updated_at", os.time(), { persist = true })
  return true
end

local function clear_runtime_host(device)
  device:set_field("runtime_host", nil, { persist = true })
  device:set_field("runtime_host_reason", nil, { persist = true })
  device:set_field("runtime_host_updated_at", nil, { persist = true })
end



local function mark_io_success(device, source)
  device:set_field("consecutive_io_failures", 0, { persist = false })
  device:set_field("last_successful_io_at", os.time(), { persist = false })
  device:set_field("last_successful_io_source", source or "unknown", { persist = false })
  pcall(function() device:online() end)
end

local function mark_io_failure(device, source, err)
  local failures = safe_tonumber(device:get_field("consecutive_io_failures"), 0) + 1
  device:set_field("consecutive_io_failures", failures, { persist = false })
  device:set_field("last_io_error", tostring(err or "unknown"), { persist = false })
  device:set_field("last_io_error_source", tostring(source or "unknown"), { persist = false })

  -- Do not immediately mark the device offline on a single transient Tuya/LAN
  -- failure.  The Tuya air purifier sometimes appears to need one wake/refresh cycle after
  -- an idle period; marking offline too aggressively causes UI flapping and can
  -- make recovery look worse than it is.
  if failures >= 3 then
    pcall(function() device:offline() end)
  else
    log.warn(string.format("Air purifier I/O failure %d/3 before offline: source=%s err=%s", failures, tostring(source), tostring(err)))
  end
  return failures
end

local function seconds_since_success(device)
  local last = safe_tonumber(device:get_field("last_successful_io_at"), 0)
  if last <= 0 then return nil end
  return os.time() - last
end

local function tcp_rediscover(device, reason)
  if device:get_field("tcp_rediscovery_busy") then
    log.debug("Tuya TCP rediscovery already running; skipping overlapping request from " .. tostring(reason or "unknown"))
    return nil, "TCP rediscovery already running"
  end

  local device_id = device.preferences.deviceId
  local local_key = device.preferences.localKey
  local seed_host = get_manual_host(device) or get_runtime_host(device)

  if not device_id or device_id == "" or device_id == "REPLACE_WITH_DEVICE_ID" then
    return nil, "missing deviceId preference"
  end
  if not local_key or local_key == "" or local_key == "REPLACE_WITH_LOCAL_KEY" then
    return nil, "missing localKey preference"
  end
  if not seed_host or seed_host == "" then
    return nil, "missing host preference for subnet scan"
  end

  device:set_field("tcp_rediscovery_busy", true, { persist = false })
  local ok, found, err = pcall(TuyaTcpScan.scan_for, {
    device_id = device_id,
    local_key = local_key,
    seed_host = seed_host,
    timeout = 0.25,
  })
  device:set_field("tcp_rediscovery_busy", false, { persist = false })

  if not ok then return nil, tostring(found) end
  return found, err
end

local function get_settings(device)
  local host = get_runtime_host(device)
  local device_id = device.preferences.deviceId
  local local_key = device.preferences.localKey

  if not host or host == "" then return nil, "missing host preference" end
  if not device_id or device_id == "" or device_id == "REPLACE_WITH_DEVICE_ID" then return nil, "missing deviceId preference" end
  if not local_key or local_key == "" or local_key == "REPLACE_WITH_LOCAL_KEY" then return nil, "missing localKey preference" end

  return {
    host = host,
    device_id = device_id,
    local_key = local_key,
    port = 6668,
    packet_debug = device.preferences.verboseLogging == true,
  }
end

local function get_client(device)
  local existing = device:get_field("tuya_client")
  if existing then return existing end

  local opts, err = get_settings(device)
  if not opts then return nil, err end

  local client = TuyaClient.new(opts)
  device:set_field("tuya_client", client, { persist = false })
  return client
end

local function reset_client(device)
  local client = device:get_field("tuya_client")
  if client then pcall(function() client:close() end) end
  device:set_field("tuya_client", nil, { persist = false })
end

local function with_io_lock(device, label, fn)
  local waited = 0
  while device:get_field("tuya_io_busy") do
    if waited >= 12 then
      return nil, label .. " timed out waiting for Tuya I/O lock"
    end
    cosock.socket.sleep(0.1)
    waited = waited + 0.1
  end

  device:set_field("tuya_io_busy", true, { persist = false })
  local ok, result, err = pcall(fn)
  device:set_field("tuya_io_busy", false, { persist = false })

  if not ok then
    return nil, tostring(result)
  end
  if result ~= nil then
    device:set_field("last_tuya_io_at", os.time(), { persist = false })
  end
  return result, err
end

local function component(device, id)
  return device.profile and device.profile.components and device.profile.components[id]
end

local function emit_component(device, component_id, event)
  local comp = component(device, component_id)
  if comp then
    device:emit_component_event(comp, event)
  else
    log.warn("Component not found for event: " .. tostring(component_id))
  end
end

local function copy_dps_table(src)
  local copy = {}
  if src then
    for k, v in pairs(src) do
      copy[tostring(k)] = v
    end
  end
  return copy
end

local function merge_dps(device, partial)
  if not partial then return device:get_field("last_dps") or {} end
  local merged = copy_dps_table(device:get_field("last_dps") or {})
  for k, v in pairs(partial) do
    merged[tostring(k)] = v
  end
  device:set_field("last_dps", merged, { persist = false })
  return merged
end

local function emit_if_ok(label, fn)
  local ok, err = pcall(fn)
  if not ok then log.warn(label .. " event failed: " .. tostring(err)) end
end

local function emit_display_light_mode(device, tuya_value)
  if not CAP_DISPLAY_LIGHT or not CAP_DISPLAY_LIGHT.displayLightMode then return end
  local st_value = LIGHT_TUYA_TO_CUSTOM[tuya_value or "Close"] or "off"
  emit_if_ok("displayLight", function()
    emit_component(device, "displayLight", CAP_DISPLAY_LIGHT.displayLightMode({ value = st_value }))
  end)
end

local function emit_timer_state(device, tuya_timer, remaining)
  if not CAP_TIMER then return end
  local st_value = TIMER_TUYA_TO_CUSTOM[tuya_timer or "cancel"] or "off"
  local minutes = safe_tonumber(remaining, 0)
  if CAP_TIMER.timerMode then
    emit_if_ok("purifierTimer mode", function()
      emit_component(device, "timer", CAP_TIMER.timerMode({ value = st_value }))
    end)
  end
  if CAP_TIMER.timerRemaining then
    emit_if_ok("purifierTimer remaining", function()
      emit_component(device, "timer", CAP_TIMER.timerRemaining({ value = math.floor(minutes), unit = "min" }))
    end)
  end
end

local function emit_static_capability_state(device)
  -- Keep supported values hidden/noisy where possible.  Some generated capability event helpers
  -- vary between library versions, so keep each emit guarded.
  emit_if_ok("supportedAirPurifierFanModes", function()
    device:emit_event(CAP_AP_MODE.supportedAirPurifierFanModes({ value = { "auto", "high", "sleep", "off" } }, { visibility = { displayed = false } }))
  end)
  emit_if_ok("supportedFilterCommands", function()
    device:emit_event(CAP_FILTER.supportedFilterCommands({ value = { "resetFilter" } }, { visibility = { displayed = false } }))
  end)
end

local try_rediscover_host

local function emit_from_dps(device, dps, source)
  if not dps then return end

  local previous = copy_dps_table(device:get_field("last_dps") or {})
  local merged = merge_dps(device, dps)

  -- v0.8.1 diagnostic/stability pass:
  -- Do not periodically re-emit unchanged visible capability state as a
  -- keepalive.  Scheduled refreshes should emit real DPS changes only.
  -- Important: previous must be a snapshot, not the live last_dps table,
  -- otherwise merge_dps mutates the same table before comparison and every
  -- background refresh looks unchanged.
  --
  -- Manual refresh, initial refresh, and verified command refresh still
  -- force-visible state so the user can explicitly resync the app card when
  -- needed.
  local force_visible_emit = (source == "command" or source == "initial" or source == "manualRefresh")

  local function changed(dp)
    return dps[dp] ~= nil and (previous[dp] ~= dps[dp] or force_visible_emit)
  end

  if changed("1") then
    device:emit_event(merged["1"] and CAP_SWITCH.switch.on() or CAP_SWITCH.switch.off())
  end

  if changed("3") or changed("1") then
    local st_mode = merged["1"] == false and "off" or (MODE_TUYA_TO_ST[merged["3"]] or "auto")
    emit_if_ok("airPurifierFanMode", function()
      device:emit_event(CAP_AP_MODE.airPurifierFanMode({ value = st_mode }))
    end)
  end

  if changed("2") then
    local pm25 = safe_tonumber(merged["2"], nil)
    if pm25 then
      emit_if_ok("fineDustLevel", function()
        device:emit_event(CAP_PM25.fineDustLevel({ value = math.floor(pm25), unit = "μg/m^3" }))
      end)
    end
  end

  if changed("21") then
    local aq = AQ_TUYA_TO_ST[merged["21"]] or "unknown"
    emit_if_ok("airQualityHealthConcern", function()
      device:emit_event(CAP_AQ.airQualityHealthConcern({ value = aq }))
    end)
  end

  if changed("5") then
    local filter = safe_tonumber(merged["5"], nil)
    if filter then
      emit_if_ok("filterLifeRemaining", function()
        device:emit_event(CAP_FILTER.filterLifeRemaining({ value = math.floor(filter), unit = "%" }))
      end)
    end
  end

  if changed("6") then
    emit_component(device, "ionizer", merged["6"] and CAP_SWITCH.switch.on() or CAP_SWITCH.switch.off())
  end

  if changed("9") then
    emit_component(device, "uv", merged["9"] and CAP_SWITCH.switch.on() or CAP_SWITCH.switch.off())
  end

  if changed("101") then
    local light_mode = merged["101"] or "Close"
    emit_display_light_mode(device, light_mode)
  end

  if changed("18") or changed("19") then
    local timer_mode = merged["18"] or "cancel"
    emit_timer_state(device, timer_mode, merged["19"])
  end

  log.info(string.format(
    "Air purifier DPS state[%s]: switch=%s pm25=%s mode=%s filter=%s anion=%s uv=%s timer=%s left=%s aq=%s fault=%s light=%s",
    tostring(source or "update"),
    tostring(merged["1"]), tostring(merged["2"]), tostring(merged["3"]), tostring(merged["5"]),
    tostring(merged["6"]), tostring(merged["9"]), tostring(merged["18"]), tostring(merged["19"]),
    tostring(merged["21"]), tostring(merged["22"]), tostring(merged["101"])
  ))
end

local function refresh_device(driver, device, source)
  local refresh_source = source or "refresh"
  local status, s_err = with_io_lock(device, "refresh", function()
    local client, err = get_client(device)
    if not client then return nil, err end
    return client:status()
  end)

  if not status then
    log.warn("Air purifier refresh failed: " .. tostring(s_err))
    reset_client(device)
    local failures = mark_io_failure(device, "refresh", s_err)

    -- Only run the relatively expensive TCP rediscovery after repeated failures
    -- and only when all required preferences exist.  Missing preferences during
    -- setup must not start a scan.
    if failures >= 2 then
      local new_host = try_rediscover_host(device, "refresh failure")
      if new_host then
        local retry_status, retry_err = with_io_lock(device, "refresh retry after IP rediscovery", function()
          local client, err = get_client(device)
          if not client then return nil, err end
          return client:status()
        end)
        if retry_status then
          mark_io_success(device, "rediscovery refresh")
          emit_from_dps(device, retry_status.dps, "rediscovery")
          return
        end
        log.warn("Air purifier refresh retry after IP rediscovery failed: " .. tostring(retry_err))
        reset_client(device)
        mark_io_failure(device, "rediscovery refresh retry", retry_err)
      end
    end
    return
  end

  mark_io_success(device, refresh_source)
  emit_from_dps(device, status.dps, refresh_source)
end


try_rediscover_host = function(device, reason)
  if not auto_rediscovery_enabled(device) then
    log.debug("Tuya IP rediscovery disabled; not searching after " .. tostring(reason or "request"))
    return nil, "auto rediscovery disabled"
  end

  local device_id = device.preferences.deviceId
  if not device_id or device_id == "" or device_id == "REPLACE_WITH_DEVICE_ID" then
    return nil, "missing deviceId preference"
  end

  log.info("Tuya TCP rediscovery scanning local /24 for Tuya air purifier deviceId=" .. tostring(device_id) .. " after " .. tostring(reason or "request"))
  local found, err = tcp_rediscover(device, reason or "rediscovery")
  if not found then
    log.warn("Tuya TCP rediscovery did not find matching Tuya air purifier: " .. tostring(err))
    return nil, err
  end

  local ip = found.ip
  if not ip or ip == "" then
    return nil, "matching TCP probe had no IP"
  end

  local manual = get_manual_host(device)
  local old_effective = get_runtime_host(device)
  local changed = set_runtime_host(device, ip, "tcp-scan")
  if changed then
    log.info(string.format(
      "Tuya TCP rediscovery matched Tuya air purifier deviceId=%s at %s (manual=%s previousEffective=%s); using discovered host",
      tostring(device_id), tostring(ip), tostring(manual), tostring(old_effective)
    ))
    reset_client(device)
  else
    log.debug("Tuya TCP rediscovery confirmed Tuya air purifier still at " .. tostring(ip))
  end

  return ip
end

local function discovery_loop(driver, device)
  -- v0.7 tried to listen for Tuya UDP broadcasts on ports 6666/6667/7000,
  -- but current SmartThings Edge hub sandboxing can reject binding specific
  -- inbound UDP ports with "forbidden".  Do not run a noisy background
  -- listener.  v0.8.1 performs conservative TCP probing only after the
  -- normal configured host fails.
  if device:get_field("discovery_notice_logged") then return end
  device:set_field("discovery_notice_logged", true, { persist = false })
  log.info("Air purifier IP rediscovery is enabled as TCP failover scan; passive UDP listener disabled on this hub environment")
end

local function next_poll_generation(device)
  local generation = safe_tonumber(device:get_field("poll_generation"), 0) + 1
  device:set_field("poll_generation", generation, { persist = false })
  return generation
end

local function current_poll_generation(device)
  return safe_tonumber(device:get_field("poll_generation"), 0)
end

local function next_ingress_seq(device, kind, label)
  local seq = safe_tonumber(device:get_field("ingress_seq"), 0) + 1
  device:set_field("ingress_seq", seq, { persist = false })
  device:set_field("last_ingress_kind", tostring(kind or "capability"), { persist = false })
  device:set_field("last_ingress_label", tostring(label or "unknown"), { persist = false })
  device:set_field("last_ingress_at", os.time(), { persist = false })
  return seq
end

local function cancel_poll_timer(device)
  local timer = device:get_field("poll_timer")
  if timer then
    pcall(function() device.thread:cancel_timer(timer) end)
    device:set_field("poll_timer", nil, { persist = false })
  end
  device:set_field("poll_interval_active", nil, { persist = false })
  -- Invalidate already-scheduled callbacks that may still fire after an
  -- infoChanged/init transition.  The callback checks this token before doing
  -- any Tuya I/O, which keeps us at one active logical poll loop.
  next_poll_generation(device)
end

local function run_scheduled_poll(driver, device, generation)
  if generation and generation ~= current_poll_generation(device) then
    log.debug("Skipping stale scheduled poll generation " .. tostring(generation) .. "; active=" .. tostring(current_poll_generation(device)))
    return
  end

  local now = os.time()
  local last_heartbeat = safe_tonumber(device:get_field("last_driver_heartbeat_at"), 0)
  if now - last_heartbeat >= 300 then
    device:set_field("last_driver_heartbeat_at", now, { persist = false })
    local since = seconds_since_success(device)
    log.info("Air purifier driver heartbeat: poll loop alive, secondsSinceIoSuccess=" .. tostring(since or "never") .. ", failures=" .. tostring(safe_tonumber(device:get_field("consecutive_io_failures"), 0)))
  end

  local opts, pref_err = get_settings(device)
  if not opts then
    log.warn("Monitor waiting for preferences: " .. tostring(pref_err))
    return
  end

  -- Command handlers should never get stuck behind a background poll.  If the
  -- user/App is currently driving Tuya I/O, skip this tick and let the next
  -- scheduled run catch up.
  if device:get_field("tuya_io_busy") then
    log.debug("Skipping scheduled poll because Tuya I/O is busy")
    return
  end

  local interval = safe_tonumber(device.preferences.pollInterval, 30)
  if interval < 5 then interval = 5 end
  local last_io = safe_tonumber(device:get_field("last_tuya_io_at"), 0)
  now = os.time()
  -- Avoid an immediate duplicate refresh right after a command-triggered verification.
  if now - last_io < math.min(interval, 5) then
    log.debug("Skipping scheduled poll because recent Tuya I/O already refreshed state")
    return
  end

  refresh_device(driver, device, "refresh")
end

local function monitor_loop(driver, device)
  local interval = safe_tonumber(device.preferences.pollInterval, 30)
  if interval < 5 then interval = 5 end

  local active_interval = safe_tonumber(device:get_field("poll_interval_active"), nil)
  if device:get_field("poll_timer") and active_interval == interval then
    return
  end

  cancel_poll_timer(device)
  local generation = next_poll_generation(device)
  log.info("Starting Tuya air purifier scheduled poll timer at " .. tostring(interval) .. "s generation=" .. tostring(generation))
  local timer = device.thread:call_on_schedule(interval, function()
    run_scheduled_poll(driver, device, generation)
  end, "tuya-air-purifier-poll-monitor")
  device:set_field("poll_timer", timer, { persist = false })
  device:set_field("poll_interval_active", interval, { persist = false })
end

local function discovery_handler(driver, opts, cont)
  for _, dev in ipairs(driver:get_devices()) do
    if dev.device_network_id == DNI then
      log.info("Air Purifier setup device already exists")
      return
    end
  end

  log.info("Creating Air Purifier manual setup device")
  local metadata = {
    type = "LAN",
    device_network_id = DNI,
    label = "Air Purifier",
    profile = "tuya-air-purifier",
    manufacturer = "Tuya",
    model = "Air Purifier v3.3",
    vendor_provided_label = "Air Purifier",
  }
  driver:try_create_device(metadata)
end

local function device_added(driver, device)
  log.info("Air Purifier device added; open Settings and enter host/deviceId/localKey. IP rediscovery can update the runtime host after setup.")
  emit_static_capability_state(device)
  device:emit_event(CAP_SWITCH.switch.off())
  emit_component(device, "ionizer", CAP_SWITCH.switch.off())
  emit_component(device, "uv", CAP_SWITCH.switch.off())
  emit_display_light_mode(device, "Close")
  emit_timer_state(device, "cancel", 0)
end

local function device_init(driver, device)
  log.info("Air Purifier device init")
  emit_static_capability_state(device)
  monitor_loop(driver, device)
  discovery_loop(driver, device)
end

local function device_removed(driver, device)
  log.info("Air Purifier device removed")
  cancel_poll_timer(device)
  reset_client(device)
end

local function command_attempt(device, dps, label, attempt)
  local client, err = get_client(device)
  if not client then return nil, err end

  -- If the device has been idle or we already had failures, do a lightweight
  -- status query before the command.  This doubles as a Tuya LAN "wake" probe
  -- without changing device state.  The returned DPS is not emitted here to keep
  -- command logging simple; the verified status after the command is authoritative.
  local idle = seconds_since_success(device)
  local failures = safe_tonumber(device:get_field("consecutive_io_failures"), 0)
  if attempt > 1 or failures > 0 or (idle and idle > 90) then
    local warm, warm_err = client:status()
    if warm and warm.dps then
      log.debug("Air purifier wake/status probe before " .. label .. " succeeded")
    else
      log.warn("Air purifier wake/status probe before " .. label .. " failed: " .. tostring(warm_err))
      reset_client(device)
      client, err = get_client(device)
      if not client then return nil, err end
    end
    cosock.socket.sleep(0.25)
  end

  local ack, ack_err = client:set_dps(dps)
  if not ack then return nil, ack_err end

  cosock.socket.sleep(attempt == 1 and 0.9 or 1.2)
  local verified, verify_err = client:status()
  if verified and verified.dps then return verified end

  log.warn("Command verification status failed after " .. label .. ": " .. tostring(verify_err))
  if ack.dps then return ack end
  return { dps = dps }
end

local function dps_transaction(device, dps, label, seq)
  log.info("Air purifier command start seq=" .. tostring(seq or "?") .. ": " .. tostring(label))
  local last_err
  for attempt = 1, 2 do
    local status, s_err = with_io_lock(device, label .. " attempt " .. attempt, function()
      return command_attempt(device, dps, label, attempt)
    end)

    if status then
      mark_io_success(device, label)
      emit_from_dps(device, status.dps, "command")
      log.info("Air purifier command complete seq=" .. tostring(seq or "?") .. ": " .. tostring(label))
      return status
    end

    last_err = s_err
    log.warn(label .. " attempt " .. attempt .. " failed: " .. tostring(s_err))
    reset_client(device)
    cosock.socket.sleep(0.6)
  end

  local failures = mark_io_failure(device, label, last_err)

  -- If the command failed repeatedly, a stale DHCP address is possible.  Try the
  -- TCP rediscovery path only after at least two consecutive I/O failures, then
  -- retry the command once against the discovered runtime host.
  if failures >= 2 then
    local new_host = try_rediscover_host(device, label .. " command failure")
    if new_host then
      local retry_status, retry_err = with_io_lock(device, label .. " retry after IP rediscovery", function()
        return command_attempt(device, dps, label .. " after rediscovery", 2)
      end)
      if retry_status then
        mark_io_success(device, label .. " rediscovery retry")
        emit_from_dps(device, retry_status.dps, "command")
        log.info("Air purifier command complete after rediscovery seq=" .. tostring(seq or "?") .. ": " .. tostring(label))
        return retry_status
      end
      last_err = retry_err
      mark_io_failure(device, label .. " rediscovery retry", retry_err)
    end
  end

  log.warn(label .. " failed after retries: " .. tostring(last_err))
  return nil, last_err
end


local function safe_task_name(label)
  local text = tostring(label or "command"):gsub("[^%w%-_]+", "-")
  if #text > 48 then text = text:sub(1, 48) end
  return text
end

local function optimistic_merge_and_emit(device, dps, label)
  -- v0.7.8: acknowledge SmartThings commands immediately.  The real Tuya
  -- command and verification run asynchronously, then correct/confirm state.
  -- This is intentionally limited to the affected DPS values so unsupported
  -- fields cannot be invented locally.
  if not dps then return end
  log.debug("Air purifier optimistic state emit for " .. tostring(label))
  emit_from_dps(device, dps, "optimistic")
end

local function run_async_dps_transaction(driver, device, dps, label)
  local seq = next_ingress_seq(device, "command", label)
  log.info("Air purifier command ingress seq=" .. tostring(seq) .. " queued for async Tuya verification: " .. tostring(label))
  optimistic_merge_and_emit(device, dps, label)

  cosock.spawn(function()
    log.info("Air purifier async Tuya verification start seq=" .. tostring(seq) .. ": " .. tostring(label))
    local ok, result, err = pcall(function()
      return dps_transaction(device, dps, label, seq)
    end)

    if ok and result then
      log.info("Air purifier async Tuya verification complete seq=" .. tostring(seq) .. ": " .. tostring(label))
      return
    end

    local failure = ok and err or result
    log.warn("Air purifier async Tuya verification failed seq=" .. tostring(seq) .. " for " .. tostring(label) .. ": " .. tostring(failure))

    -- If an optimistic command could not be verified, do a best-effort refresh
    -- to restore the UI to the real purifier state.  refresh_device already
    -- handles I/O failures and rediscovery/backoff accounting.
    local refresh_ok, refresh_err = pcall(function()
      refresh_device(driver, device, "correctiveRefresh")
    end)
    if not refresh_ok then
      log.warn("Air purifier corrective refresh after async command failure failed: " .. tostring(refresh_err))
    end
  end, "tuya-air-purifier-async-" .. safe_task_name(label))

  log.info("Air purifier command handler returning immediately seq=" .. tostring(seq) .. ": " .. tostring(label))
end

local function run_async_refresh(driver, device, label)
  local refresh_label = label or "refresh"
  local seq = next_ingress_seq(device, "refresh", refresh_label)
  log.info("Air purifier refresh ingress seq=" .. tostring(seq) .. " queued for async Tuya I/O: " .. tostring(refresh_label))
  cosock.spawn(function()
    log.info("Air purifier async refresh start seq=" .. tostring(seq) .. ": " .. tostring(refresh_label))
    local ok, err = pcall(function()
      refresh_device(driver, device, "manualRefresh")
    end)
    if ok then
      log.info("Air purifier async refresh complete seq=" .. tostring(seq) .. ": " .. tostring(refresh_label))
    else
      log.warn("Air purifier async refresh failed seq=" .. tostring(seq) .. ": " .. tostring(err))
    end
  end, "tuya-air-purifier-refresh-" .. safe_task_name(refresh_label))
  log.info("Air purifier refresh handler returning immediately seq=" .. tostring(seq) .. ": " .. tostring(refresh_label))
end

local function switch_handler(driver, device, command)
  local component_id = command.component or "main"
  local on = command.command == "on"

  if component_id == "main" then
    run_async_dps_transaction(driver, device, { ["1"] = on }, "main switch " .. command.command)
  elseif component_id == "ionizer" then
    run_async_dps_transaction(driver, device, { ["6"] = on }, "ionizer " .. command.command)
  elseif component_id == "uv" then
    run_async_dps_transaction(driver, device, { ["9"] = on }, "uv " .. command.command)
  else
    log.warn("Unhandled switch component: " .. tostring(component_id))
  end
end

local function set_display_light_mode(driver, device, command)
  local mode = command.args and command.args.displayLightMode
  local tuya_value = LIGHT_CUSTOM_TO_TUYA[mode]
  if not tuya_value then
    log.warn("Unsupported display light mode: " .. tostring(mode))
    return
  end
  run_async_dps_transaction(driver, device, { ["101"] = tuya_value }, "display light mode " .. tostring(mode))
end

local function set_timer_mode(driver, device, command)
  local mode = command.args and command.args.timerMode
  local tuya_value = TIMER_CUSTOM_TO_TUYA[mode]
  if not tuya_value then
    log.warn("Unsupported timer mode: " .. tostring(mode))
    return
  end
  run_async_dps_transaction(driver, device, { ["18"] = tuya_value }, "timer mode " .. tostring(mode))
end

local function refresh_handler(driver, device, command)
  run_async_refresh(driver, device, "manual refresh")
end

local function set_air_purifier_fan_mode(driver, device, command)
  local mode = command.args and command.args.airPurifierFanMode
  local tuya_mode = MODE_ST_TO_TUYA[mode]
  if not tuya_mode then
    log.warn("Unsupported air purifier fan mode: " .. tostring(mode))
    return
  end

  if tuya_mode == "off" then
    run_async_dps_transaction(driver, device, { ["1"] = false }, "air purifier mode off")
  else
    -- Set switch and mode together so selecting a mode also turns the purifier on.
    run_async_dps_transaction(driver, device, { ["1"] = true, ["3"] = tuya_mode }, "air purifier mode " .. mode)
  end
end

local function reset_filter(driver, device, command)
  -- DP11 is intentionally exposed only as a command, not a normal switch.
  run_async_dps_transaction(driver, device, { ["11"] = true }, "filter reset")
end

local function info_changed(driver, device, event, args)
  log.info("Air Purifier preferences changed; reconnecting")
  if not auto_rediscovery_enabled(device) then
    clear_runtime_host(device)
  end
  reset_client(device)
  cancel_poll_timer(device)
  monitor_loop(driver, device)
  discovery_loop(driver, device)
  refresh_device(driver, device, "initial")
end

local capability_handlers = {
  [CAP_SWITCH.ID] = {
    [CAP_SWITCH.commands.on.NAME] = switch_handler,
    [CAP_SWITCH.commands.off.NAME] = switch_handler,
  },
  [CAP_REFRESH.ID] = {
    [CAP_REFRESH.commands.refresh.NAME] = refresh_handler,
  },
  [CAP_AP_MODE.ID] = {
    [CAP_AP_MODE.commands.setAirPurifierFanMode.NAME] = set_air_purifier_fan_mode,
  },
  [CAP_FILTER.ID] = {
    [CAP_FILTER.commands.resetFilter.NAME] = reset_filter,
  },
}

if CAP_DISPLAY_LIGHT and CAP_DISPLAY_LIGHT.ID and CAP_DISPLAY_LIGHT.commands and CAP_DISPLAY_LIGHT.commands.setDisplayLightMode then
  capability_handlers[CAP_DISPLAY_LIGHT.ID] = {
    [CAP_DISPLAY_LIGHT.commands.setDisplayLightMode.NAME] = set_display_light_mode,
  }
end

if CAP_TIMER and CAP_TIMER.ID and CAP_TIMER.commands and CAP_TIMER.commands.setTimerMode then
  capability_handlers[CAP_TIMER.ID] = {
    [CAP_TIMER.commands.setTimerMode.NAME] = set_timer_mode,
  }
end

local driver = Driver(DRIVER_NAME, {
  discovery = discovery_handler,
  lifecycle_handlers = {
    added = device_added,
    init = device_init,
    removed = device_removed,
    infoChanged = info_changed,
  },
  capability_handlers = capability_handlers,
})

driver:run()
