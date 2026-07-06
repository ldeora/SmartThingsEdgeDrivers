local cosock = require "cosock"
local http = cosock.asyncify "socket.http"
local ltn12 = require "ltn12"

local constants = require "airlink.constants"
local parser = require "airlink.parser"
local util = require "airlink.util"

local api = {}

function api.fetch_raw(host, port)
  if not util.is_non_empty_string(host) then
    return nil, "missing AirLink host"
  end

  local normalized_host, normalized_port = util.parse_host_port(host, port or constants.DEFAULT_PORT)
  normalized_port = tonumber(normalized_port) or constants.DEFAULT_PORT
  local url = string.format("http://%s:%d/v1/current_conditions", util.host_for_url(normalized_host), normalized_port)
  local chunks = {}

  local success, code, headers, status = http.request({
    url = url,
    method = "GET",
    headers = {
      ["Accept"] = "application/json",
      ["User-Agent"] = "SmartThings-Davis-AirLink-Edge/1.0.2",
    },
    sink = ltn12.sink.table(chunks),
    create = function()
      local sock = cosock.socket.tcp()
      sock:settimeout(constants.HTTP_TIMEOUT)
      return sock
    end,
  })

  if not success then
    return nil, "HTTP request failed: " .. tostring(code)
  end

  if tonumber(code) ~= 200 then
    return nil, string.format("HTTP status %s (%s)", tostring(code), tostring(status))
  end

  return table.concat(chunks), nil, headers, status
end

function api.fetch_current_conditions(host, port)
  local ok, data, err = pcall(function()
    local raw, raw_err = api.fetch_raw(host, port)
    if not raw then return nil, raw_err end
    return parser.parse_body(raw)
  end)

  if not ok then
    return nil, "AirLink API exception: " .. tostring(data)
  end

  return data, err
end

return api
