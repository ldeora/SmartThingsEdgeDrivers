local constants = require "airlink.constants"

local util = {}

function util.trim(value)
  if value == nil then return nil end
  return tostring(value):match("^%s*(.-)%s*$")
end

function util.is_non_empty_string(value)
  return type(value) == "string" and util.trim(value) ~= ""
end

function util.build_dni(did)
  if did == nil then return nil end
  local s = util.trim(did)
  if s == nil or s == "" then return nil end
  return constants.DNI_PREFIX .. s
end

function util.did_from_dni(dni)
  if type(dni) ~= "string" then return nil end

  -- Use literal prefix slicing instead of Lua patterns. The DNI prefix contains
  -- a hyphen ("davis-airlink:"), which has pattern meaning and must not be
  -- interpolated into string.match().
  local prefix = constants.DNI_PREFIX
  if dni:sub(1, #prefix) ~= prefix then return nil end

  local did = dni:sub(#prefix + 1)
  if did == "" then return nil end
  return did
end

function util.clamp_number(value, min_value, max_value, default_value)
  local n = tonumber(value)
  if n == nil then return default_value end
  if min_value ~= nil and n < min_value then n = min_value end
  if max_value ~= nil and n > max_value then n = max_value end
  return n
end

function util.get_poll_interval(device)
  local pref = nil
  if device and device.preferences then
    pref = device.preferences.pollInterval
  end
  return util.clamp_number(pref, constants.MIN_POLL_INTERVAL, constants.MAX_POLL_INTERVAL, constants.DEFAULT_POLL_INTERVAL)
end

function util.get_host_override(device)
  if device and device.preferences and util.is_non_empty_string(device.preferences.hostOverride) then
    return util.trim(device.preferences.hostOverride)
  end
  return nil
end

function util.get_debug_logging(device)
  if not device or not device.preferences then return false end
  return device.preferences.debugLogging == true or tostring(device.preferences.debugLogging) == "true"
end

function util.get_health_basis(device)
  if device and device.preferences and util.is_non_empty_string(device.preferences.healthBasis) then
    local value = util.trim(device.preferences.healthBasis)
    if value == "minute" then return "minute" end
  end
  return "nowcast"
end

function util.f_to_c(f)
  local n = tonumber(f)
  if n == nil then return nil end
  return (n - 32.0) * 5.0 / 9.0
end

function util.round(value, decimals)
  local n = tonumber(value)
  if n == nil then return nil end
  local scale = 10 ^ (decimals or 0)
  if n >= 0 then
    return math.floor(n * scale + 0.5) / scale
  end
  return math.ceil(n * scale - 0.5) / scale
end

function util.round_int_non_negative(value)
  local n = tonumber(value)
  if n == nil then return nil end
  if n < 0 then n = 0 end
  return math.floor(n + 0.5)
end

function util.floor_to_decimals(value, decimals)
  local n = tonumber(value)
  if n == nil then return nil end
  local scale = 10 ^ (decimals or 0)
  return math.floor(n * scale) / scale
end


function util.number_or_nil(value)
  local n = tonumber(value)
  if n == nil then return nil end
  -- Guard against NaN values if a Lua JSON implementation ever produces one.
  if n ~= n then return nil end
  return n
end

function util.pick_number(...)
  for i = 1, select("#", ...) do
    local n = util.number_or_nil(select(i, ...))
    if n ~= nil then return n end
  end
  return nil
end

function util.pick(...)
  for i = 1, select("#", ...) do
    local v = select(i, ...)
    if v ~= nil then return v end
  end
  return nil
end

function util.safe_tostring(value)
  if value == nil then return "nil" end
  return tostring(value)
end

function util.table_len(t)
  if type(t) ~= "table" then return 0 end
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  return n
end

function util.find_device_by_dni(driver, dni)
  if not driver or not dni then return nil end
  local devices = driver:get_devices() or {}
  for _, device in pairs(devices) do
    if device and device.device_network_id == dni then
      return device
    end
  end
  return nil
end

function util.is_ipv4(address)
  if type(address) ~= "string" then return false end
  local a, b, c, d = address:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
  a, b, c, d = tonumber(a), tonumber(b), tonumber(c), tonumber(d)
  if not a or not b or not c or not d then return false end
  return a <= 255 and b <= 255 and c <= 255 and d <= 255
end


function util.parse_host_port(host, fallback_port)
  local h = util.trim(host)
  if h == nil or h == "" then
    return h, tonumber(fallback_port) or constants.DEFAULT_PORT
  end

  -- Be forgiving in the static-host preference: users sometimes paste a full URL.
  h = h:gsub("^https?://", "")
  h = h:gsub("/.*$", "")

  local port = tonumber(fallback_port) or constants.DEFAULT_PORT

  -- Bracketed IPv6 with port: [fe80::1]:80
  local bracket_host, bracket_port = h:match("^%[(.-)%]:(%d+)$")
  if bracket_host then
    return bracket_host, tonumber(bracket_port) or port
  end

  -- Bracketed IPv6 without port: [fe80::1]
  local bracket_only = h:match("^%[(.-)%]$")
  if bracket_only then
    return bracket_only, port
  end

  -- Hostname/IPv4 with port. Avoid interpreting bare IPv6 addresses as host:port.
  if not h:find(":.*:") then
    local host_part, port_part = h:match("^(.-):(%d+)$")
    if util.is_non_empty_string(host_part) and port_part then
      return util.trim(host_part), tonumber(port_part) or port
    end
  end

  return h, port
end

function util.host_for_url(host)
  if type(host) ~= "string" then return host end
  if host:find(":", 1, true) and not host:match("^%[.*%]$") then
    return "[" .. host .. "]"
  end
  return host
end

return util
