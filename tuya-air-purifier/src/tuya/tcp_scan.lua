-- Conservative TCP-based IP rediscovery for Tuya v3.3 air purifier devices.
--
-- Why TCP scan instead of passive UDP?
--   Tuya devices broadcast discovery packets to UDP 6666/6667/7000, but on
--   some SmartThings Edge hub environments drivers cannot bind those specific
--   inbound ports (error: "forbidden").  The working TCP Tuya protocol path is
--   therefore used as a fallback: probe TCP/6668 on the same /24 as the manual
--   Host/IP preference and accept only an address that answers a Tuya status
--   query with the configured Device ID and Local Key.
--
-- Scope:
--   * Only used after the configured/runtime host fails.
--   * Only scans the /24 of the manual Host/IP preference.
--   * Uses short timeouts so the scan is bounded, but it can still take a while on networks that silently drop TCP attempts.
--   * v0.7.x keeps the timeout deliberately low and only starts scanning after
--     repeated normal I/O failures.

local log = require "log"
local TuyaClient = require "tuya.client"

local scanner = {}

local function parse_ipv4(host)
  local a, b, c, d = tostring(host or ""):match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$")
  a, b, c, d = tonumber(a or ""), tonumber(b or ""), tonumber(c or ""), tonumber(d or "")
  if not (a and b and c and d) then return nil end
  if a > 255 or b > 255 or c > 255 or d > 255 then return nil end
  return a, b, c, d
end

local function make_ip(a, b, c, d)
  return string.format("%d.%d.%d.%d", a, b, c, d)
end

local function candidate_hosts(seed_host)
  local a, b, c, d = parse_ipv4(seed_host)
  if not a then return nil, "Host/IP is not an IPv4 address, cannot derive /24 scan range" end

  local candidates = {}
  local seen = {}
  local function add(last)
    if last < 1 or last > 254 then return end
    local ip = make_ip(a, b, c, last)
    if not seen[ip] then
      seen[ip] = true
      candidates[#candidates + 1] = ip
    end
  end

  -- Try the old/manual address first, then nearby DHCP neighbours, then the
  -- rest of the /24.  This finds common DHCP moves quickly without relying on
  -- router-specific lease APIs.
  add(d)
  for offset = 1, 25 do
    add(d - offset)
    add(d + offset)
  end
  for last = 1, 254 do add(last) end
  return candidates
end

function scanner.scan_for(opts)
  local device_id = opts and opts.device_id
  local local_key = opts and opts.local_key
  local seed_host = opts and opts.seed_host
  local timeout_value = opts and opts.timeout
  local timeout = timeout_value and tonumber(timeout_value) or 0.25

  if not device_id or device_id == "" then return nil, "missing device_id" end
  if not local_key or local_key == "" then return nil, "missing local_key" end

  local candidates, c_err = candidate_hosts(seed_host)
  if not candidates then return nil, c_err end

  log.info(string.format("Tuya TCP rediscovery probing %d candidates in subnet of %s", #candidates, tostring(seed_host)))

  local failures = 0
  for idx, ip in ipairs(candidates) do
    local client = TuyaClient.new({
      host = ip,
      port = 6668,
      device_id = device_id,
      local_key = local_key,
      timeout = timeout,
    })

    local status, err = client:status()
    pcall(function() client:close() end)

    if status and status.dps then
      log.info(string.format("Tuya TCP rediscovery verified matching Tuya air purifier at %s after %d probes", ip, idx))
      return { ip = ip, dps = status.dps }
    end

    failures = failures + 1
    if failures == 1 or failures == 25 or failures == 75 or failures == 150 then
      log.debug(string.format("Tuya TCP rediscovery progress: %d/%d candidates tried; last=%s err=%s", idx, #candidates, ip, tostring(err)))
    end
  end

  return nil, "no matching Tuya TCP status response in /24 of " .. tostring(seed_host)
end

return scanner
