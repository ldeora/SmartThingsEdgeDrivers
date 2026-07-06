local mdns = require "st.mdns"
local log = require "log"

local api = require "airlink.api"
local constants = require "airlink.constants"
local util = require "airlink.util"

local discovery = {}

-- Network data for devices that were just created during this driver run.
-- try_create_device does not give us the new Device object immediately, so
-- added/init handlers consume this cache and persist the discovery result there.
local pending_devices = {}

local function candidate_key(host, port)
  return tostring(host or "") .. ":" .. tostring(port or constants.DEFAULT_PORT)
end

local function select_host(host_info)
  if type(host_info) ~= "table" then return nil end

  local address = util.trim(host_info.address)
  local name = util.trim(host_info.name)

  -- Prefer IPv4 addresses because SmartThings hubs and consumer routers tend to
  -- handle them most consistently for local HTTP device APIs. If mDNS only gives
  -- IPv6, prefer the resolvable hostname over a raw link-local IPv6 URL.
  if util.is_ipv4(address) then return address end
  if util.is_non_empty_string(name) then return name end
  if util.is_non_empty_string(address) then return address end
  return nil
end

local function service_matches(found)
  if type(found) ~= "table" then return false end
  local si = found.service_info
  if type(si) ~= "table" then return true end

  local name = si.name
  local service_type = si.service_type

  if name == nil and service_type == nil then return true end
  if name == constants.MDNS_SERVICE_TYPE or service_type == constants.MDNS_SERVICE_TYPE then return true end
  if type(name) == "string" and name:find(constants.MDNS_SERVICE_TYPE, 1, true) then return true end
  if type(service_type) == "string" and service_type:find(constants.MDNS_SERVICE_TYPE, 1, true) then return true end

  return false
end

function discovery.discover_candidates()
  local response, err = mdns.discover(constants.MDNS_SERVICE_TYPE, constants.MDNS_DOMAIN)
  if not response then
    log.warn(string.format("AirLink mDNS discovery returned no response: %s", tostring(err)))
    return {}
  end

  local found_list = response.found or response
  if type(found_list) ~= "table" then
    log.warn("AirLink mDNS discovery response did not contain a usable found list")
    return {}
  end

  local candidates = {}
  local seen = {}

  for _, found in pairs(found_list) do
    if service_matches(found) and type(found.host_info) == "table" then
      local host_info = found.host_info
      local host = select_host(host_info)
      local port = tonumber(host_info.port) or constants.DEFAULT_PORT

      if util.is_non_empty_string(host) then
        local key = candidate_key(host, port)
        if not seen[key] then
          seen[key] = true
          table.insert(candidates, {
            host = util.trim(host),
            port = port,
            host_name = host_info.name,
            address = host_info.address,
          })
        end
      end
    end
  end

  table.sort(candidates, function(a, b)
    local a_ipv4 = util.is_ipv4(a.host)
    local b_ipv4 = util.is_ipv4(b.host)
    if a_ipv4 ~= b_ipv4 then return a_ipv4 end
    return tostring(a.host) < tostring(b.host)
  end)

  log.info(string.format("AirLink mDNS discovery found %d candidate(s)", #candidates))
  for _, c in ipairs(candidates) do
    log.info(string.format("AirLink mDNS candidate host=%s port=%s host_name=%s address=%s", tostring(c.host), tostring(c.port), tostring(c.host_name), tostring(c.address)))
  end

  return candidates
end

local function save_network_fields(device, host, port, did, name)
  if not device then return end
  if host then device:set_field(constants.FIELD_HOST, host, { persist = true }) end
  if port then device:set_field(constants.FIELD_PORT, tonumber(port) or constants.DEFAULT_PORT, { persist = true }) end
  if did then device:set_field(constants.FIELD_DID, tostring(did), { persist = true }) end
  if name then device:set_field(constants.FIELD_NAME, tostring(name), { persist = true }) end
end

discovery.save_network_fields = save_network_fields

function discovery.remember_pending_device(dni, host, port, did, name)
  if not dni then return end
  pending_devices[dni] = {
    host = host,
    port = tonumber(port) or constants.DEFAULT_PORT,
    did = did,
    name = name,
  }
end

function discovery.apply_pending_fields(device)
  if not device then return false end
  local dni = device.device_network_id
  local pending = dni and pending_devices[dni]
  if not pending then return false end

  save_network_fields(device, pending.host, pending.port, pending.did, pending.name)
  pending_devices[dni] = nil

  log.info(string.format(
    "Applied pending AirLink discovery fields DNI=%s host=%s port=%s did=%s name=%s",
    tostring(dni), tostring(pending.host), tostring(pending.port), tostring(pending.did), tostring(pending.name)
  ))
  return true
end

function discovery.create_or_update_from_candidate(driver, candidate)
  if type(candidate) ~= "table" then return nil, "invalid candidate" end

  local data, err = api.fetch_current_conditions(candidate.host, candidate.port)
  if not data then
    return nil, string.format("validation failed for host=%s port=%s: %s", tostring(candidate.host), tostring(candidate.port), tostring(err))
  end

  local dni = util.build_dni(data.did)
  if not dni then
    return nil, "validated candidate but did could not be converted into DNI"
  end

  local existing = util.find_device_by_dni(driver, dni)
  if existing then
    save_network_fields(existing, candidate.host, candidate.port, data.did, data.name)
    log.info(string.format("Updated existing Davis AirLink device did=%s name=%s host=%s port=%s", tostring(data.did), tostring(data.name), tostring(candidate.host), tostring(candidate.port)))
    return existing, nil, data
  end

  local label = data.name or "Davis AirLink"
  local metadata = {
    type = "LAN",
    device_network_id = dni,
    label = label,
    profile = constants.PROFILE_NAME,
    manufacturer = "Davis Instruments",
    model = "AirLink",
    vendor_provided_label = label,
    external_id = tostring(data.did),
  }

  discovery.remember_pending_device(dni, candidate.host, candidate.port, data.did, data.name)

  local ok, create_err = pcall(function()
    driver:try_create_device(metadata)
  end)

  if not ok then
    pending_devices[dni] = nil
    return nil, "try_create_device failed: " .. tostring(create_err)
  end

  log.info(string.format("Requested creation of Davis AirLink did=%s name=%s host=%s port=%s DNI=%s", tostring(data.did), tostring(data.name), tostring(candidate.host), tostring(candidate.port), dni))
  return nil, nil, data
end

function discovery.handle_discovery(driver, _, should_continue)
  log.info("Starting Davis AirLink LAN discovery")
  local candidates = discovery.discover_candidates()

  for _, candidate in ipairs(candidates) do
    if should_continue and should_continue() == false then
      log.info("Davis AirLink discovery stopped by platform")
      return
    end

    local _, err, data = discovery.create_or_update_from_candidate(driver, candidate)
    if err then
      log.warn("Davis AirLink discovery candidate rejected: " .. tostring(err))
    elseif data then
      log.info(string.format("Davis AirLink discovery validated did=%s data_structure_type=%s", tostring(data.did), tostring(data.condition and data.condition.data_structure_type)))
    end
  end

  if #candidates == 0 then
    log.warn("No Davis AirLink mDNS candidates found. Check that the AirLink and SmartThings hub are on the same LAN/VLAN and that mDNS is not blocked.")
  end
end

function discovery.rediscover_existing_device(driver, device)
  if not device then return false, "missing device" end

  local wanted_did = device:get_field(constants.FIELD_DID) or util.did_from_dni(device.device_network_id)
  if not wanted_did then
    return false, "cannot rediscover without known did"
  end

  local candidates = discovery.discover_candidates()
  for _, candidate in ipairs(candidates) do
    local data, err = api.fetch_current_conditions(candidate.host, candidate.port)
    if data and tostring(data.did) == tostring(wanted_did) then
      save_network_fields(device, candidate.host, candidate.port, data.did, data.name)
      log.info(string.format("Rediscovered Davis AirLink did=%s at host=%s port=%s", tostring(data.did), tostring(candidate.host), tostring(candidate.port)))
      return true, nil
    elseif err then
      log.debug(string.format("Rediscovery candidate host=%s port=%s failed: %s", tostring(candidate.host), tostring(candidate.port), tostring(err)))
    end
  end

  return false, "matching AirLink did not appear in mDNS discovery"
end

return discovery
