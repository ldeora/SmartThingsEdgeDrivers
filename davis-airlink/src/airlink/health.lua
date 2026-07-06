local constants = require "airlink.constants"
local util = require "airlink.util"

local health = {}

local function pct_ok(value)
  local n = tonumber(value)
  return n ~= nil and n >= 75
end

local function category_from_pm25(value)
  local c = util.floor_to_decimals(value, 1)
  if c == nil then return constants.HEALTH_UNKNOWN end

  -- US EPA/AirNow 2024 PM2.5 AQI concentration breakpoints mapped to
  -- SmartThings health concern strings. This driver emits a category only,
  -- not a numeric AQI value.
  if c <= 9.0 then return constants.HEALTH_GOOD end
  if c <= 35.4 then return constants.HEALTH_MODERATE end
  if c <= 55.4 then return constants.HEALTH_SLIGHTLY_UNHEALTHY end
  if c <= 125.4 then return constants.HEALTH_UNHEALTHY end
  if c <= 225.4 then return constants.HEALTH_VERY_UNHEALTHY end
  return constants.HEALTH_HAZARDOUS
end

local function category_from_pm10(value)
  local c = util.floor_to_decimals(value, 0)
  if c == nil then return constants.HEALTH_UNKNOWN end

  -- US EPA/AirNow PM10 AQI concentration breakpoints mapped to
  -- SmartThings health concern strings.
  if c <= 54 then return constants.HEALTH_GOOD end
  if c <= 154 then return constants.HEALTH_MODERATE end
  if c <= 254 then return constants.HEALTH_SLIGHTLY_UNHEALTHY end
  if c <= 354 then return constants.HEALTH_UNHEALTHY end
  if c <= 424 then return constants.HEALTH_VERY_UNHEALTHY end
  return constants.HEALTH_HAZARDOUS
end

local function worse(a, b)
  local ra = constants.HEALTH_RANK[a or constants.HEALTH_UNKNOWN] or 0
  local rb = constants.HEALTH_RANK[b or constants.HEALTH_UNKNOWN] or 0
  if rb > ra then return b end
  return a
end

local function select_pm25(condition, basis)
  if basis == "minute" then
    return util.pick_number(condition.pm25, condition.pm25_last)
  end

  if condition.pm25_nowcast ~= nil and pct_ok(condition.pct_nowcast) then
    return condition.pm25_nowcast
  end
  if condition.pm25_1h ~= nil and pct_ok(condition.pct_1h) then
    return condition.pm25_1h
  end
  return util.pick_number(condition.pm25, condition.pm25_last)
end

local function select_pm10(condition, basis)
  if basis == "minute" then
    return util.pick_number(condition.pm10, condition.pm10_last)
  end

  if condition.pm10_nowcast ~= nil and pct_ok(condition.pct_nowcast) then
    return condition.pm10_nowcast
  end
  if condition.pm10_1h ~= nil and pct_ok(condition.pct_1h) then
    return condition.pm10_1h
  end
  return util.pick_number(condition.pm10, condition.pm10_last)
end

function health.calculate(condition, basis)
  if type(condition) ~= "table" then
    return {
      very_fine = constants.HEALTH_UNKNOWN,
      fine = constants.HEALTH_UNKNOWN,
      dust = constants.HEALTH_UNKNOWN,
      overall = constants.HEALTH_UNKNOWN,
      basis = basis or "unknown",
    }
  end

  local effective_basis = basis or "nowcast"
  local pm25_for_health = select_pm25(condition, effective_basis)
  local pm10_for_health = select_pm10(condition, effective_basis)

  local very_fine = category_from_pm25(util.pick_number(condition.pm1, condition.pm1_last))
  local fine = category_from_pm25(pm25_for_health)
  local dust = category_from_pm10(pm10_for_health)
  local overall = worse(fine, dust)

  return {
    very_fine = very_fine,
    fine = fine,
    dust = dust,
    overall = overall,
    basis = effective_basis,
    pm25_for_health = pm25_for_health,
    pm10_for_health = pm10_for_health,
  }
end

return health
