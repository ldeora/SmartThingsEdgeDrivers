-- SONOFF Hydro ONE / Hydro ONE Lite / Hydro DUO helper functions

local cluster_base = require "st.zigbee.cluster_base"
local data_types = require "st.zigbee.data_types"

local utils = {}

utils.SONOFF_MFG_CODE = 0x1286 -- 4742 decimal / Shenzhen CoolKit Technology Co., Ltd.
utils.EWELINK_CLUSTER_ID = 0xFC11
utils.UNKNOWN_PRIVATE_CLUSTER_ID = 0xFC57

utils.ATTR_CHILD_LOCK = 0x0000
utils.ATTR_REAL_TIME_IRRIGATION_DURATION = 0x5006
utils.ATTR_REAL_TIME_IRRIGATION_VOLUME = 0x5007
utils.ATTR_VALVE_ABNORMAL_STATE = 0x500C
utils.ATTR_VALVE_WORK_STATE = 0x5010 -- observed by ZHA on related firmware; optional on Hydro ONE
utils.ATTR_RAIN_DELAY_END_DATETIME = 0x5014
utils.ATTR_HOUR_IRRIGATION_VOLUME = 0x501B
utils.ATTR_HOUR_IRRIGATION_DURATION = 0x501C
utils.ATTR_MANUAL_DEFAULT_SETTINGS = 0x501D
utils.ATTR_SEASONAL_WATERING_ADJUSTMENT = 0x501E
utils.ATTR_IRRIGATION_SCHEDULE_STATUS = 0x501F
utils.ATTR_VALVE_ALARM_SETTINGS = 0x5020
utils.ATTR_UNIT_OF_WATER_FLOW = 0x5021

-- New-firmware 0x5021 mapping. Note that the unit byte inside 0x501D keeps
-- the separate irrigation mapping 0=US gallon, 1=litre, 2=imperial gallon.
utils.WATER_FLOW_UNIT_BY_CODE = {
  [0] = "liter",
  [1] = "us_gallon",
  [2] = "imperial_gallon",
}

-- Bit layout used by valve_abnormal_state 0x500C on single-channel Hydro ONE
utils.ABNORMAL_WATER_SHORTAGE = 0x01
utils.ABNORMAL_WATER_LEAKAGE = 0x02
utils.ABNORMAL_FROST_PROTECTION = 0x04
utils.ABNORMAL_FAIL_SAFE = 0x08

-- Bit layout used by valve_abnormal_state 0x500C on Hydro DUO:
-- bit0 shortage CH1, bit1 leakage, bit2 fail-safe CH1, bit3 shortage CH2,
-- bit4 fail-safe CH2, bit5 frost CH1, bit6 frost CH2, bit7 high flow.
utils.DUO_ABNORMAL_WATER_SHORTAGE_CH1 = 0x01
utils.DUO_ABNORMAL_WATER_LEAKAGE = 0x02
utils.DUO_ABNORMAL_FAIL_SAFE_CH1 = 0x04
utils.DUO_ABNORMAL_WATER_SHORTAGE_CH2 = 0x08
utils.DUO_ABNORMAL_FAIL_SAFE_CH2 = 0x10
utils.DUO_ABNORMAL_FROST_CH1 = 0x20
utils.DUO_ABNORMAL_FROST_CH2 = 0x40
utils.DUO_ABNORMAL_HIGH_FLOW = 0x80

-- Bit layout in valve_alarm_settings 0x5020 byte 0
utils.ALARM_WATER_SHORTAGE = 0x01
utils.ALARM_WATER_LEAK = 0x02
utils.ALARM_FROST_PROTECTION = 0x04
utils.ALARM_WATER_SHORTAGE_AUTO_CLOSE = 0x08
utils.ALARM_WATER_LEAK_AUTO_CLOSE = 0x10

local function as_attr_id(attr_id)
  return data_types.validate_or_build_type(attr_id, data_types.AttributeId, "attr_id")
end

local function apply_mfg_header(message, mfg_code)
  if mfg_code ~= nil then
    message.body.zcl_header.frame_ctrl:set_mfg_specific()
    message.body.zcl_header.mfg_code = data_types.validate_or_build_type(mfg_code, data_types.Uint16, "mfg_code")
  end
  return message
end

function utils.custom_read_attribute(device, cluster_id, attr_id, mfg_code)
  local message = cluster_base.read_attribute(device, data_types.ClusterId(cluster_id), as_attr_id(attr_id))
  return apply_mfg_header(message, mfg_code or utils.SONOFF_MFG_CODE)
end

function utils.custom_write_attribute(device, cluster_id, attr_id, data_type, value, mfg_code)
  local data = data_types.validate_or_build_type(value, data_type)
  local message = cluster_base.write_attribute(device, data_types.ClusterId(cluster_id), as_attr_id(attr_id), data)
  return apply_mfg_header(message, mfg_code or utils.SONOFF_MFG_CODE)
end

function utils.custom_write_attribute_data(device, cluster_id, attr_id, data, mfg_code)
  local message = cluster_base.write_attribute(device, data_types.ClusterId(cluster_id), as_attr_id(attr_id), data)
  return apply_mfg_header(message, mfg_code or utils.SONOFF_MFG_CODE)
end

function utils.standard_read_attribute(device, cluster_id, attr_id)
  return cluster_base.read_attribute(device, data_types.ClusterId(cluster_id), as_attr_id(attr_id))
end

function utils.standard_write_attribute_data(device, cluster_id, attr_id, data)
  return cluster_base.write_attribute(device, data_types.ClusterId(cluster_id), as_attr_id(attr_id), data)
end

function utils.custom_configure_reporting(device, cluster_id, attr_id, data_type_id, minimum_interval, maximum_interval, reportable_change, mfg_code)
  local message = cluster_base.configure_reporting(
    device,
    data_types.ClusterId(cluster_id),
    as_attr_id(attr_id),
    data_type_id,
    minimum_interval,
    maximum_interval,
    reportable_change
  )
  return apply_mfg_header(message, mfg_code or utils.SONOFF_MFG_CODE)
end

function utils.to_number(value)
  if type(value) == "number" then return value end
  if type(value) == "boolean" then return value and 1 or 0 end
  if type(value) == "table" then
    if type(value.value) == "number" then return value.value end
    if type(value.value) == "boolean" then return value.value and 1 or 0 end
    if type(value.data) == "number" then return value.data end
  end
  local n = tonumber(value)
  return n
end

function utils.to_bool(value)
  if type(value) == "boolean" then return value end
  local n = utils.to_number(value)
  if n ~= nil then return n ~= 0 end
  if value == "true" or value == "on" or value == "enabled" or value == "locked" then return true end
  return false
end

function utils.byte_swap_u32(value)
  local n = utils.to_number(value) or 0
  local b0 = n & 0xFF
  local b1 = (n >> 8) & 0xFF
  local b2 = (n >> 16) & 0xFF
  local b3 = (n >> 24) & 0xFF
  return ((b0 << 24) | (b1 << 16) | (b2 << 8) | b3) & 0xFFFFFFFF
end


function utils.decode_u32_adaptive(value, max_plausible, prefer_when_both)
  -- Some SONOFF Hydro ONE private uint32 values have been observed through Edge
  -- in both byte orders depending on the report/read path. ZHA treats 0x5006
  -- and 0x5007 as big-endian payloads, but real test screenshots showed a
  -- normal-looking raw value (23) that became an impossible 0x17000000 after
  -- unconditional byte swapping. Pick the plausible interpretation and log both.
  local raw = utils.to_number(value) or 0
  local swapped = utils.byte_swap_u32(raw)
  local max = max_plausible or 100000
  local raw_ok = raw >= 0 and raw <= max
  local swapped_ok = swapped >= 0 and swapped <= max

  if raw_ok and not swapped_ok then
    return raw, raw, swapped, "raw"
  end
  if swapped_ok and not raw_ok then
    return swapped, raw, swapped, "swapped"
  end
  if raw_ok and swapped_ok then
    if prefer_when_both == "raw" then
      return raw, raw, swapped, "raw/both-plausible"
    end
    return swapped, raw, swapped, "swapped/both-plausible"
  end

  -- Last-resort sanity fallback. Never emit a multi-hundred-million minute
  -- irrigation duration if the alternate interpretation is at least smaller.
  if swapped < raw then
    return swapped, raw, swapped, "swapped/fallback-min"
  end
  return raw, raw, swapped, "raw/fallback-min"
end


function utils.clamp_int(value, min_value, max_value, default_value)
  local n = tonumber(value)
  if n == nil then n = default_value or min_value end
  n = math.floor(n + 0.5)
  if n < min_value then return min_value end
  if n > max_value then return max_value end
  return n
end

function utils.enabled_disabled(value)
  return value and "enabled" or "disabled"
end

function utils.set_or_clear_bit(byte, bit, enabled)
  byte = byte or 0
  if enabled then
    return byte | bit
  end
  return byte & (~bit & 0xFF)
end

function utils.get_arg(command, name, index, default_value)
  if command and command.args then
    if command.args[name] ~= nil then return command.args[name] end
    if command.args[index] ~= nil then return command.args[index] end
  end
  return default_value
end

-- Convert decoded ZCL Array values from the Edge library into a plain byte array.
-- The exact decoded shape depends on the runtime data type implementation, so this is deliberately tolerant.
function utils.array_to_bytes(value)
  local bytes = {}

  local function add_one(v)
    if v == nil then return end
    if type(v) == "number" then
      table.insert(bytes, v & 0xFF)
    elseif type(v) == "boolean" then
      table.insert(bytes, v and 1 or 0)
    elseif type(v) == "table" then
      if type(v.value) == "number" then
        table.insert(bytes, v.value & 0xFF)
      elseif type(v.value) == "boolean" then
        table.insert(bytes, v.value and 1 or 0)
      elseif type(v.value) == "table" then
        for _, e in ipairs(v.value) do add_one(e) end
      elseif type(v.elements) == "table" then
        for _, e in ipairs(v.elements) do add_one(e) end
      elseif type(v.values) == "table" then
        for _, e in ipairs(v.values) do add_one(e) end
      else
        for _, e in ipairs(v) do add_one(e) end
      end
    end
  end

  add_one(value)
  return bytes
end

local function uint8_array_fallback(bytes)
  -- Minimal standard ZCL Array object for a homogeneous array of Uint8 values.
  -- Standard ZCL array payload = element data type (0x20), element count
  -- (uint16 LE), then each Uint8 element.  This is kept for generic/non-Sonoff
  -- use, but eWeLink 0xFC11 arrays use a non-standard one-byte count and must
  -- use ewelink_uint8_array_fallback() below.
  local obj = {
    NAME = "Array",
    ID = data_types.Array.ID,
    value = bytes,
  }

  function obj:serialize()
    local out = string.char(data_types.Uint8.ID, #self.value & 0xFF, (#self.value >> 8) & 0xFF)
    for _, b in ipairs(self.value) do
      out = out .. string.char(b & 0xFF)
    end
    return out
  end

  function obj:get_length()
    return 3 + #self.value
  end

  function obj:pretty_print()
    local parts = {}
    for i, b in ipairs(self.value) do
      parts[i] = string.format("0x%02X", b & 0xFF)
    end
    return "Array<Uint8>[" .. table.concat(parts, ", ") .. "]"
  end

  return obj
end

local function ewelink_uint8_array_fallback(bytes)
  -- SONOFF/eWeLink private cluster 0xFC11 advertises several custom attributes
  -- as ZCL Array (0x48). Some early experiments assumed a one-byte element
  -- count, while hardware-verified
  -- ZHA work now confirms that 0x501D uses the standard uint16 little-endian
  -- array count. This helper remains only for backward-compatible experiments
  -- with other private attributes.
  --
  -- Kept for defensive experiments with other eWeLink array attributes.
  -- Do not use this for manual_default_settings 0x501D in the current test path:
  -- alpha13 used a Sonoff private array marker (0x48) and one-byte count
  -- for manual_default_settings 0x501D. The current path uses an explicit
  -- standard Array<Uint8> serializer with a uint16 count and no manufacturer code.
  local obj = {
    NAME = "Array",
    ID = data_types.Array.ID,
    value = bytes,
  }

  function obj:serialize()
    local out = string.char(data_types.Uint8.ID, #self.value & 0xFF)
    for _, b in ipairs(self.value) do
      out = out .. string.char(b & 0xFF)
    end
    return out
  end

  function obj:get_length()
    return 2 + #self.value
  end

  function obj:pretty_print()
    local parts = {}
    for i, b in ipairs(self.value) do
      parts[i] = string.format("0x%02X", b & 0xFF)
    end
    return "eWeLinkArray<Uint8>[" .. table.concat(parts, ", ") .. "]"
  end

  return obj
end


local function sonoff_private_array_fallback(bytes)
  -- Real Hydro ONE readback for 0x501D and 0x5020 is not a standard ZCL Array
  -- value. The device returns an outer attribute data type 0x48, followed by
  -- another 0x48 marker, a one-byte element count, then the raw bytes:
  --
  --   48 <count> <payload...>
  --
  -- This helper remains available for diagnostics and controlled experiments.
  -- Alpha14 does not use it for 0x501D because current Zigbee2MQTT writes a
  -- standard ZCL Array<Uint8> and differs primarily in the logical payload.
  local obj = {
    NAME = "Array",
    ID = data_types.Array.ID,
    value = bytes,
  }

  function obj:serialize()
    local out = string.char(data_types.Array.ID, #self.value & 0xFF)
    for _, b in ipairs(self.value) do
      out = out .. string.char(b & 0xFF)
    end
    return out
  end

  function obj:get_length()
    return 2 + #self.value
  end

  function obj:pretty_print()
    local parts = {}
    for i, b in ipairs(self.value) do
      parts[i] = string.format("0x%02X", b & 0xFF)
    end
    return "SonoffPrivateArray[" .. table.concat(parts, ", ") .. "]"
  end

  return obj
end



function utils.build_ewelink_uint8_array(bytes)
  local plain = {}
  for i, b in ipairs(bytes) do
    plain[i] = b & 0xFF
  end

  if #plain > 0xFF then
    error("eWeLink Uint8 array payload too long: " .. tostring(#plain))
  end

  return ewelink_uint8_array_fallback(plain)
end


function utils.build_sonoff_private_array(bytes)
  local plain = {}
  for i, b in ipairs(bytes) do
    plain[i] = b & 0xFF
  end

  if #plain > 0xFF then
    error("Sonoff private array payload too long: " .. tostring(#plain))
  end

  return sonoff_private_array_fallback(plain)
end



function utils.build_explicit_uint8_array(bytes)
  -- Always use the explicit serializer instead of the runtime Array constructor.
  -- The resulting value bytes are exactly:
  --   20 <count-low> <count-high> <elements...>
  -- cluster_base.write_attribute adds the outer attribute type 0x48.
  local plain = {}
  for i, b in ipairs(bytes) do
    plain[i] = b & 0xFF
  end

  if #plain > 0xFFFF then
    error("Uint8 array payload too long: " .. tostring(#plain))
  end

  return uint8_array_fallback(plain)
end

function utils.build_uint8_array(bytes)
  local typed = {}
  local plain = {}
  for i, b in ipairs(bytes) do
    local value = b & 0xFF
    typed[i] = data_types.validate_or_build_type(value, data_types.Uint8)
    plain[i] = value
  end

  local ok, data = pcall(data_types.validate_or_build_type, typed, data_types.Array)
  if ok and data ~= nil then return data end

  ok, data = pcall(data_types.Array, typed)
  if ok and data ~= nil then return data end

  -- Some Edge runtime versions are picky about constructing Array values directly.
  -- Fall back to a tiny object that has the fields/methods expected by WriteAttribute.
  return uint8_array_fallback(plain)
end

return utils
