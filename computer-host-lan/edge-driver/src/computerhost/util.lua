local C = require "computerhost.constants"
local M = {}
function M.trim(s)
  if s == nil then return nil end
  return tostring(s):match("^%s*(.-)%s*$")
end
function M.nonempty(s) return type(s) == "string" and M.trim(s) ~= "" end
function M.uuid_valid(s)
  if type(s) ~= "string" or #s ~= 36 or not s:match("^[%da-fA-F%-]+$") then return false end
  return s:sub(9,9) == "-" and s:sub(14,14) == "-" and s:sub(19,19) == "-" and s:sub(24,24) == "-"
    and #s:gsub("-", "") == 32
end
function M.dni(uuid)
  if not M.uuid_valid(uuid) then return nil end
  return C.DNI_PREFIX .. uuid:lower()
end
function M.uuid_from_dni(dni)
  if type(dni) ~= "string" or dni:sub(1, #C.DNI_PREFIX) ~= C.DNI_PREFIX then return nil end
  local uuid = dni:sub(#C.DNI_PREFIX+1)
  return M.uuid_valid(uuid) and uuid:lower() or nil
end
function M.is_ipv4(addr)
  if type(addr) ~= "string" then return false end
  local a,b,c,d = addr:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
  a,b,c,d = tonumber(a),tonumber(b),tonumber(c),tonumber(d)
  return a ~= nil and b ~= nil and c ~= nil and d ~= nil and a <= 255 and b <= 255 and c <= 255 and d <= 255
end
function M.host_for_url(host)
  if host:find(":",1,true) and not host:match("^%[.*%]$") then return "["..host.."]" end
  return host
end
function M.parse_host_port(value, fallback_port)
  local host = M.trim(value)
  local port = tonumber(fallback_port) or C.DEFAULT_PORT
  if not M.nonempty(host) then return nil, port end
  host = host:gsub("^https?://", ""):gsub("/.*$", "")
  local inner,p = host:match("^%[(.-)%]:(%d+)$")
  if inner then host=inner; port=tonumber(p)
  else
    local just = host:match("^%[(.-)%]$")
    if just then host=just
    elseif not host:find(":.*:") then
      local h,pr = host:match("^(.-):(%d+)$")
      if h and M.nonempty(h) then host=h; port=tonumber(pr) end
    end
  end
  if port < 1 or port > 65535 then return nil, C.DEFAULT_PORT end
  return host, port
end
function M.poll_interval(device)
  local v=tonumber(device.preferences and device.preferences.pollInterval) or C.DEFAULT_POLL_INTERVAL
  return math.max(10,math.min(300,math.floor(v)))
end
function M.telemetry_interval(device)
  local v=tonumber(device.preferences and device.preferences.telemetryInterval) or C.DEFAULT_TELEMETRY_INTERVAL
  return math.max(30,math.min(3600,math.floor(v)))
end
function M.assume_off_when_unreachable(device)
  -- Upgraded devices may not yet have received this preference. Default to
  -- the behavior requested for the main switch: OFF after host timeout.
  local value=device.preferences and device.preferences.assumeOffWhenUnreachable
  return value==nil or value==true or value=="true"
end
function M.failure_threshold(device)
  local v=tonumber(device.preferences and device.preferences.failureThreshold) or 3
  return math.max(2,math.min(10,math.floor(v)))
end
function M.boolean_pref(device,key)
  local val=device.preferences and device.preferences[key]
  return val==true or val=="true"
end
function M.key(device)
  local val=device.preferences and device.preferences.controlKey or ""
  val=M.trim(val) or ""
  if #val==64 and val:match("^[0-9a-fA-F]+$") then return val:lower() end
  return nil
end
-- Pure, reusable unicast MAC validation (no socket module dependency).
function M.valid_wol_mac(address)
  if type(address)~="string" then return false end
  local compact=address:gsub("[-:]",""):lower()
  if #compact~=12 or not compact:match("^[0-9a-f]+$") then return false end
  local first=tonumber(compact:sub(1,2),16)
  return (first & 1)==0 and compact~="000000000000"
end
function M.wol_mac(device)
  local val=device.preferences and device.preferences.wolMacOverride
  return M.nonempty(val) and M.trim(val) or device:get_field(C.FIELD_MAC)
end
function M.wol_broadcast(device)
  local val=device.preferences and device.preferences.wolBroadcastOverride
  return M.nonempty(val) and M.trim(val) or device:get_field(C.FIELD_BROADCAST) or "255.255.255.255"
end
function M.wol_port(device)
  local port=tonumber(device.preferences and device.preferences.wolPort) or 9
  return math.max(1,math.min(65535,math.floor(port)))
end
function M.host_override(device)
  local s = device.preferences and device.preferences.hostOverride
  return M.nonempty(s) and M.trim(s) or nil
end
function M.debug(device)
  local v = device.preferences and device.preferences.debugLogging
  return v == true or v == "true"
end
function M.find_device(driver,dni)
  for _,dev in pairs(driver:get_devices() or {}) do
    if dev.device_network_id == dni then return dev end
  end
  return nil
end
return M
