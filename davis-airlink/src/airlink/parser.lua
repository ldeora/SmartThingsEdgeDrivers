local json = require "st.json"
local log = require "log"

local util = require "airlink.util"

local parser = {}

local function decode_json(body)
  local ok, decoded = pcall(json.decode, body)
  if not ok then
    return nil, "JSON decode failed: " .. tostring(decoded)
  end
  if type(decoded) ~= "table" then
    return nil, "JSON root is not an object"
  end
  return decoded, nil
end

local function first_condition(data)
  if type(data) ~= "table" then return nil end
  if type(data.conditions) ~= "table" then return nil end
  for _, condition in ipairs(data.conditions) do
    if type(condition) == "table" then return condition end
  end
  return nil
end

function parser.normalize_condition(condition)
  if type(condition) ~= "table" then
    return nil, "condition is not an object"
  end

  return {
    lsid = util.number_or_nil(condition.lsid),
    data_structure_type = util.number_or_nil(condition.data_structure_type),

    temp_f = util.number_or_nil(condition.temp),
    humidity = util.number_or_nil(condition.hum),
    dew_point_f = util.number_or_nil(condition.dew_point),
    wet_bulb_f = util.number_or_nil(condition.wet_bulb),
    heat_index_f = util.number_or_nil(condition.heat_index),

    -- Preferred displayed values: one-minute rolling averages, fallback to last valid readings.
    -- Use numeric picking instead of nil-only picking because st.json/null-like sentinels
    -- can otherwise block valid fallback values and produce an "unknown" health state.
    pm1 = util.pick_number(condition.pm_1, condition.pm_1_last),
    pm25 = util.pick_number(condition.pm_2p5, condition.pm_2p5_last),
    pm10 = util.pick_number(condition.pm_10, condition.pm_10p0, condition.pm_10_last, condition.pm_10p0_last),

    pm1_last = util.number_or_nil(condition.pm_1_last),
    pm25_last = util.number_or_nil(condition.pm_2p5_last),
    pm10_last = util.pick_number(condition.pm_10_last, condition.pm_10p0_last),

    pm25_1h = util.number_or_nil(condition.pm_2p5_last_1_hour),
    pm25_3h = util.number_or_nil(condition.pm_2p5_last_3_hours),
    pm25_nowcast = util.number_or_nil(condition.pm_2p5_nowcast),
    pm25_24h = util.number_or_nil(condition.pm_2p5_last_24_hours),

    pm10_1h = util.pick_number(condition.pm_10_last_1_hour, condition.pm_10p0_last_1_hour),
    pm10_3h = util.pick_number(condition.pm_10_last_3_hours, condition.pm_10p0_last_3_hours),
    pm10_nowcast = util.pick_number(condition.pm_10_nowcast, condition.pm_10p0_nowcast),
    pm10_24h = util.pick_number(condition.pm_10_last_24_hours, condition.pm_10p0_last_24_hours),

    last_report_time = util.number_or_nil(condition.last_report_time),
    pct_1h = util.number_or_nil(condition.pct_pm_data_last_1_hour),
    pct_3h = util.number_or_nil(condition.pct_pm_data_last_3_hours),
    pct_nowcast = util.number_or_nil(condition.pct_pm_data_nowcast),
    pct_24h = util.number_or_nil(condition.pct_pm_data_last_24_hours),
  }, nil
end

function parser.parse_body(body)
  if type(body) ~= "string" or body == "" then
    return nil, "empty HTTP body"
  end

  local root, err = decode_json(body)
  if not root then return nil, err end

  if root.error ~= nil then
    local msg = "AirLink API returned error"
    if type(root.error) == "table" then
      msg = string.format("AirLink API error code=%s message=%s", util.safe_tostring(root.error.code), util.safe_tostring(root.error.message))
    else
      msg = msg .. ": " .. tostring(root.error)
    end
    return nil, msg
  end

  if type(root.data) ~= "table" then
    return nil, "missing data object"
  end

  local condition = first_condition(root.data)
  if not condition then
    return nil, "missing first conditions object"
  end

  local normalized, norm_err = parser.normalize_condition(condition)
  if not normalized then return nil, norm_err end

  local did = root.data.did
  if did == nil or tostring(did) == "" then
    return nil, "missing device serial number (did)"
  end

  local result = {
    did = tostring(did),
    name = root.data.name and tostring(root.data.name) or nil,
    ts = root.data.ts,
    condition = normalized,
    raw_condition = condition,
  }

  local dst = tonumber(normalized.data_structure_type)
  if dst ~= 6 and dst ~= 5 then
    log.warn(string.format("AirLink: unexpected data_structure_type=%s; continuing defensively", util.safe_tostring(normalized.data_structure_type)))
  end

  return result, nil
end

return parser
