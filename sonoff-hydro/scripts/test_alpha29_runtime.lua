-- Focused runtime regression harness for v1.4.0-alpha29.
-- Loads the actual driver with minimal SmartThings mocks and exercises the
-- recovery architecture and ordering paths changed in alpha29. Run from the driver root with:
--   texlua scripts/test_alpha29_runtime.lua

local function assert_eq(actual, expected, label)
  if actual ~= expected then
    error(string.format("%s: expected %s, got %s", label, tostring(expected), tostring(actual)), 2)
  end
end

local function assert_true(value, label)
  if not value then error(label or "assertion failed", 2) end
end

local function event(name, value)
  return { name = name, value = value }
end

local function generic_attribute(name)
  return setmetatable({}, {
    __index = function(_, key)
      return function(arg) return event(name .. "." .. tostring(key), arg) end
    end,
    __call = function(_, arg) return event(name, arg) end,
  })
end

local function generic_capability(id)
  local commands = setmetatable({}, {
    __index = function(t, key)
      local value = { NAME = key }
      rawset(t, key, value)
      return value
    end,
  })
  return setmetatable({ ID = id, commands = commands }, {
    __index = function(t, key)
      local value = generic_attribute(id .. "." .. tostring(key))
      rawset(t, key, value)
      return value
    end,
  })
end

local capabilities = setmetatable({}, {
  __index = function(t, key)
    local value = generic_capability(key)
    rawset(t, key, value)
    return value
  end,
})
capabilities.switch = generic_capability("switch")
capabilities.switch.commands.on = { NAME = "on" }
capabilities.switch.commands.off = { NAME = "off" }
capabilities.switch.switch = {
  on = function() return event("switch", "on") end,
  off = function() return event("switch", "off") end,
}
capabilities.valve = generic_capability("valve")
capabilities.valve.commands.open = { NAME = "open" }
capabilities.valve.commands.close = { NAME = "close" }
capabilities.valve.valve = {
  open = function() return event("valve", "open") end,
  closed = function() return event("valve", "closed") end,
}
capabilities.battery = generic_capability("battery")
capabilities.battery.battery = function(value) return event("battery", value) end
capabilities.waterSensor = generic_capability("waterSensor")
capabilities.waterSensor.water = {
  wet = function() return event("water", "wet") end,
  dry = function() return event("water", "dry") end,
}
capabilities.refresh = generic_capability("refresh")
capabilities.refresh.commands.refresh = { NAME = "refresh" }
capabilities.healthCheck = generic_capability("healthCheck")
capabilities.firmwareUpdate = generic_capability("firmwareUpdate")
capabilities.firmwareUpdate.currentVersion = function(value) return event("firmware", value) end

local function zcl_attribute(id, name)
  return {
    ID = id,
    read = function(_, device) return { kind = "read", name = name } end,
    configure_reporting = function(_, device, min, max) return { kind = "configure", name = name, min = min, max = max } end,
  }
end

local Basic = { ID = 0x0000, attributes = { SWBuildID = zcl_attribute(0x4000, "SWBuildID") } }
local OnOff = {
  ID = 0x0006,
  attributes = { OnOff = zcl_attribute(0x0000, "OnOff") },
  server = { commands = {
    On = function(device) return { kind = "On" } end,
    Off = function(device) return { kind = "Off" } end,
  } },
}
local PowerConfiguration = { ID = 0x0001, attributes = { BatteryPercentageRemaining = zcl_attribute(0x0021, "BatteryPercentageRemaining") } }
local PollControl = { ID = 0x0020 }
local clusters = { Basic = Basic, OnOff = OnOff, PowerConfiguration = PowerConfiguration, PollControl = PollControl }

local global_commands = {
  ReportAttribute = { ID = 0x0A },
  ReadAttributeResponse = { ID = 0x01 },
  WriteAttributeResponse = { ID = 0x04 },
  DefaultResponse = { ID = 0x0B },
}

local data_types = {
  Uint8 = { ID = 0x20 },
  Array = { ID = 0x48 },
}

local utils = {
  EWELINK_CLUSTER_ID = 0xFC11,
  SONOFF_MFG_CODE = 0x1286,
  ATTR_MANUAL_DEFAULT_SETTINGS = 0x501D,
  ATTR_UNIT_OF_WATER_FLOW = 0x5021,
  ATTR_CHILD_LOCK = 0x0000,
  ATTR_REAL_TIME_IRRIGATION_DURATION = 0x5006,
  ATTR_REAL_TIME_IRRIGATION_VOLUME = 0x5007,
  ATTR_VALVE_ABNORMAL_STATE = 0x5008,
  ATTR_VALVE_WORK_STATE = 0x5009,
  ATTR_HOUR_IRRIGATION_DURATION = 0x500A,
  ATTR_HOUR_IRRIGATION_VOLUME = 0x500B,
  ATTR_VALVE_ALARM_SETTINGS = 0x5020,
  WATER_FLOW_UNIT_BY_CODE = { [0] = "liter", [1] = "us_gallon", [2] = "imperial_gallon" },
  ABNORMAL_WATER_SHORTAGE = 0x01,
  ABNORMAL_WATER_LEAKAGE = 0x02,
  ABNORMAL_FROST_PROTECTION = 0x20,
  ABNORMAL_FAIL_SAFE = 0x04,
  DUO_ABNORMAL_WATER_SHORTAGE_CH1 = 0x01,
  DUO_ABNORMAL_WATER_SHORTAGE_CH2 = 0x08,
  DUO_ABNORMAL_WATER_LEAKAGE = 0x02,
  DUO_ABNORMAL_FAIL_SAFE_CH1 = 0x04,
  DUO_ABNORMAL_FAIL_SAFE_CH2 = 0x10,
  DUO_ABNORMAL_FROST_CH1 = 0x20,
  DUO_ABNORMAL_FROST_CH2 = 0x40,
  DUO_ABNORMAL_HIGH_FLOW = 0x80,
  ALARM_WATER_SHORTAGE = 0x01,
  ALARM_WATER_LEAK = 0x02,
  ALARM_FROST_PROTECTION = 0x20,
}

function utils.clamp_int(value, minimum, maximum, fallback)
  local n = tonumber(value)
  if n == nil then n = fallback end
  n = math.floor(n + 0.5)
  if n < minimum then n = minimum end
  if n > maximum then n = maximum end
  return n
end
function utils.to_bool(value)
  if type(value) == "table" and value.value ~= nil then value = value.value end
  return value == true or value == 1 or value == "1" or value == "on" or value == "open"
end
function utils.to_number(value)
  if type(value) == "table" and value.value ~= nil then value = value.value end
  return tonumber(value)
end
function utils.get_arg(command, name, index, fallback)
  if command and command.args then return command.args[name] or command.args[index] or fallback end
  return fallback
end
function utils.array_to_bytes(value) return value end
function utils.decode_u32_adaptive(value) return tonumber(value) or 0, tonumber(value) or 0, tonumber(value) or 0, "raw" end
function utils.standard_read_attribute(device, cluster_id, attr_id)
  return { kind = "privateRead", cluster = cluster_id, attr = attr_id }
end
function utils.custom_read_attribute(device, cluster_id, attr_id, mfg)
  return { kind = "privateReadMfg", cluster = cluster_id, attr = attr_id, mfg = mfg }
end
function utils.standard_write_attribute_data(device, cluster_id, attr_id, value)
  return { kind = "privateWrite", cluster = cluster_id, attr = attr_id, value = value }
end
function utils.custom_write_attribute_data(device, cluster_id, attr_id, value, mfg)
  return { kind = "privateWriteMfg", cluster = cluster_id, attr = attr_id, value = value, mfg = mfg }
end
function utils.build_explicit_uint8_array(bytes)
  return {
    bytes = bytes,
    serialize = function(self)
      local chars = { string.char(0x20, #self.bytes & 0xFF, (#self.bytes >> 8) & 0xFF) }
      for _, b in ipairs(self.bytes) do table.insert(chars, string.char(b & 0xFF)) end
      return table.concat(chars)
    end,
  }
end

function utils.build_uint8_array(bytes)
  return { bytes = bytes }
end

function utils.set_or_clear_bit(value, bit, enabled)
  value = tonumber(value) or 0
  if enabled then return value | bit end
  return value & (~bit & 0xFF)
end
function utils.enabled_disabled(value) return value and "enabled" or "disabled" end

setmetatable(utils, {
  __index = function(t, key)
    if key:match("^[A-Z0-9_]+$") then
      local value = 0x6000 + #key
      rawset(t, key, value)
      return value
    end
    local fn = function(...) return { kind = key, args = { ... } } end
    rawset(t, key, fn)
    return fn
  end,
})

local captured_template
local function ZigbeeDriver(name, template)
  captured_template = template
  return { run = function() end }
end

package.preload["st.capabilities"] = function() return capabilities end
package.preload["st.zigbee"] = function() return ZigbeeDriver end
package.preload["st.zigbee.zcl.clusters"] = function() return clusters end
package.preload["st.zigbee.zcl.global_commands"] = function() return global_commands end
package.preload["st.zigbee.data_types"] = function() return data_types end
package.preload["st.zigbee.device_management"] = function()
  return { build_bind_request = function(device, cluster, eui) return { kind = "bind", cluster = cluster } end }
end
package.preload["sonoff_utils"] = function() return utils end

local function load_driver()
  captured_template = nil
  local chunk, err = loadfile("src/init.lua")
  assert(chunk, err)
  chunk()
  assert(captured_template, "driver template was not captured")
  return captured_template
end

local function new_device()
  local device = {
    fields = {}, sent = {}, attempted = {}, events = {}, timers = {}, actions = {},
    preferences = { manualDuration = 10, debugLogging = false, shortageAlarm = "disabled", leakAlarm = "disabled", frostAlarm = "disabled", shortageAutoClose = "disabled", leakAutoClose = "disabled", shortageDuration = 1, leakDuration = 1, frostThreshold = 5 },
    profile = { name = "sonoff-hydro-one" },
    model = "SWV-ZFE",
  }
  function device:get_field(key) return self.fields[key] end
  function device:set_field(key, value, options) self.fields[key] = value end
  function device:get_model() return self.model end
  function device:get_manufacturer() return "SONOFF" end
  function device:configure() self.configure_called = true end
  function device:set_component_to_endpoint_fn(fn) self.component_to_endpoint = fn end
  function device:set_endpoint_to_component_fn(fn) self.endpoint_to_component = fn end
  function device:emit_event(evt)
    if self.fail_events then error("injected event failure") end
    table.insert(self.events, evt)
  end
  function device:emit_event_for_endpoint(endpoint, evt)
    if self.fail_events then error("injected event failure") end
    table.insert(self.events, { endpoint = endpoint, event = evt })
  end
  function device:send(msg)
    table.insert(self.actions, { kind = "send", message = msg })
    table.insert(self.attempted, msg)
    if self.fail_on and msg and msg.kind == "On" then error("injected On failure") end
    if self.fail_off and msg and msg.kind == "Off" then error("injected Off failure") end
    table.insert(self.sent, msg)
  end
  function device:send_to_component(component, msg)
    msg.component = component
    self:send(msg)
  end
  device.thread = {
    call_with_delay = function(_, seconds, callback)
      table.insert(device.actions, { kind = "timer", seconds = seconds })
      table.insert(device.timers, { seconds = seconds, callback = callback })
      return #device.timers
    end,
  }
  return device
end

local template = load_driver()
local function lifecycle(name, device, ...)
  return template.lifecycle_handlers[name](nil, device, ...)
end
local function command(capability, command_name, device, payload)
  return template.capability_handlers[capability][command_name](nil, device, payload or { component = "main", args = {} })
end

local function onoff_report(device, value, endpoint)
  local report = { address_header = { src_endpoint = { value = endpoint or 1 } } }
  template.zigbee_handlers.attr[OnOff.ID][OnOff.attributes.OnOff.ID](nil, device, value, report)
end

local function private_record(device, command_id, attr_id, value, endpoint)
  local response = {
    address_header = { src_endpoint = { value = endpoint or 1 } },
    body = { zcl_body = { attr_records = {
      { attr_id = { value = attr_id }, data = { value = value } },
    } } },
  }
  template.zigbee_handlers.global[utils.EWELINK_CLUSTER_ID][command_id](nil, device, response)
end

local function settings_report(device, bytes, endpoint)
  private_record(device, global_commands.ReportAttribute.ID, utils.ATTR_MANUAL_DEFAULT_SETTINGS, bytes, endpoint)
end
local function settings_read_response(device, bytes, endpoint)
  private_record(device, global_commands.ReadAttributeResponse.ID, utils.ATTR_MANUAL_DEFAULT_SETTINGS, bytes, endpoint)
end
local function alarm_report(device, bytes, endpoint)
  private_record(device, global_commands.ReportAttribute.ID, utils.ATTR_VALVE_ALARM_SETTINGS, bytes, endpoint)
end
local function alarm_read_response(device, bytes, endpoint)
  private_record(device, global_commands.ReadAttributeResponse.ID, utils.ATTR_VALVE_ALARM_SETTINGS, bytes, endpoint)
end

local function find_timers(device, seconds)
  local out = {}
  for _, timer in ipairs(device.timers) do
    if seconds == nil or timer.seconds == seconds then table.insert(out, timer) end
  end
  return out
end
local function last_timer(device, seconds)
  local timers = find_timers(device, seconds)
  return timers[#timers]
end
local function count_kind(device, kind)
  local count = 0
  for _, msg in ipairs(device.attempted) do if msg and msg.kind == kind then count = count + 1 end end
  return count
end
local function count_private_attr(device, kind, attr)
  local count = 0
  for _, msg in ipairs(device.attempted) do
    if msg and msg.kind == kind and msg.attr == attr then count = count + 1 end
  end
  return count
end
local function first_action_index(device, kind, detail)
  for i, action in ipairs(device.actions) do
    if action.kind == kind then
      if kind == "timer" and (detail == nil or action.seconds == detail) then return i end
      if kind == "send" and action.message and (detail == nil or action.message.kind == detail) then return i end
    end
  end
end
local function confirm_closed(device, endpoint)
  onoff_report(device, 0, endpoint or 1)
end
local function value_contains(value, needle, depth)
  depth = depth or 0
  if depth > 6 then return false end
  if type(value) == "table" then
    for k, v in pairs(value) do
      if value_contains(k, needle, depth + 1) or value_contains(v, needle, depth + 1) then return true end
    end
    return false
  end
  return tostring(value):find(needle, 1, true) ~= nil
end
local function event_contains(device, needle)
  for _, evt in ipairs(device.events) do if value_contains(evt, needle) then return true end end
  return false
end


local passed = 0
local function test(name, fn)
  fn()
  passed = passed + 1
  print(string.format("ok %02d - %s", passed, name))
end

test("normal Valve Open queues standard On first and no private command", function()
  local d = new_device()
  command("valve", "open", d)
  assert_eq(d.attempted[1].kind, "On", "first command")
  assert_eq(count_private_attr(d, "privateRead", utils.ATTR_MANUAL_DEFAULT_SETTINGS), 0, "no 0x501D read")
  assert_eq(count_kind(d, "privateWrite"), 0, "no private write")
end)

test("normal Switch On uses the same standard On path", function()
  local d = new_device()
  command("switch", "on", d)
  assert_eq(d.attempted[1].kind, "On", "first command")
end)

test("normal Close queues standard Off first", function()
  local d = new_device()
  command("valve", "close", d)
  assert_eq(d.attempted[1].kind, "Off", "first command")
end)

test("post-On UI failure cannot undo or fail a queued Zigbee On", function()
  local d = new_device(); d.fail_events = true
  local ok = pcall(command, "valve", "open", d)
  assert_true(ok, "secondary UI exception contained")
  assert_eq(count_kind(d, "On"), 1, "On queued")
end)

test("actual Zigbee On send failure still propagates", function()
  local d = new_device(); d.fail_on = true
  local ok = pcall(command, "valve", "open", d)
  assert_true(not ok, "send error must propagate")
end)

test("timed watering arms delayed Off before standard On", function()
  local d = new_device()
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=5} })
  assert_true(first_action_index(d, "timer", 300) < first_action_index(d, "send", "On"), "timer before On")
  assert_eq(d.fields["timed_session_active:main"], true, "active")
  assert_eq(d.fields["timed_recovery_required:main"], true, "recovery persisted")
  assert_eq(count_private_attr(d, "privateRead", utils.ATTR_MANUAL_DEFAULT_SETTINGS), 0, "no private read")
end)

test("timed callback queues standard Off", function()
  local d = new_device()
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=2} })
  local before=count_kind(d,"Off")
  last_timer(d,120).callback()
  assert_eq(count_kind(d,"Off"),before+1,"timer Off")
  assert_eq(d.fields["timed_session_active:main"],false,"inactive")
  assert_eq(d.fields["timed_recovery_required:main"],false,"recovery cleared")
end)

test("successful timed replacement invalidates old callback", function()
  local d = new_device()
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=5} })
  local old=last_timer(d,300)
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=6} })
  local before=count_kind(d,"Off")
  old.callback()
  assert_eq(count_kind(d,"Off"),before,"old callback inert")
  last_timer(d,360).callback()
  assert_eq(count_kind(d,"Off"),before+1,"new callback closes")
end)

test("failed timed replacement preserves previous safety timer", function()
  local d = new_device()
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=5} })
  local old=last_timer(d,300)
  d.fail_on=true
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=6} })
  d.fail_on=false
  assert_eq(d.fields["timed_session_active:main"],true,"old session retained")
  local before=count_kind(d,"Off")
  last_timer(d,360).callback()
  assert_eq(count_kind(d,"Off"),before,"failed replacement inert")
  old.callback()
  assert_eq(count_kind(d,"Off"),before+1,"old timer still closes")
end)

test("failed manual takeover preserves an existing timed timer", function()
  local d = new_device()
  command("oceancircle09600.hydroTimedWatering", "openForMinutes", d, { component="main", args={minutes=5} })
  local old=last_timer(d,300)
  d.fail_on=true
  local ok=pcall(command,"valve","open",d)
  d.fail_on=false
  assert_true(not ok,"manual On failure surfaced")
  assert_eq(d.fields["timed_session_active:main"],true,"old timed session retained")
  local before=count_kind(d,"Off"); old.callback()
  assert_eq(count_kind(d,"Off"),before+1,"old timer closes")
end)

test("ordinary init sends no unsolicited Off or private duration read", function()
  local d=new_device(); lifecycle("init",d)
  assert_eq(count_kind(d,"Off"),0,"no recovery Off")
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),0,"untouched default does not synchronize")
  assert_true(count_kind(d,"read") >= 3,"standard state reads")
end)

test("configured non-default duration is verified independently on init", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("init",d)
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),1,"one independent 0x501D read")
  assert_eq(count_kind(d,"On"),0,"no On")
  assert_eq(count_kind(d,"Off"),0,"no Off")
end)

test("already verified duration does not create repeated startup traffic", function()
  local d=new_device(); d.preferences.manualDuration=20
  d.fields.manual_duration_user_configured=true
  d.fields.manual_default_last_sync_status="verified"
  d.fields.manual_default_confirmed_duration=20
  lifecycle("init",d)
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),0,"verified target reused")
end)

test("0x501D timeout leaves basic control working and Refresh retries", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("init",d)
  local timeout=last_timer(d,8); assert_true(timeout~=nil,"timeout armed")
  timeout.callback()
  assert_eq(d.fields.manual_default_last_sync_status,"failed","timeout status")
  command("valve","open",d)
  assert_eq(count_kind(d,"On"),1,"standard On works")
  local before=count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS)
  command("refresh","refresh",d)
  assert_true(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS)>before,"Refresh retries")
end)

test("persisted timed run is recovered with one standard Off", function()
  local d=new_device(); d.fields["timed_recovery_required:main"]=true
  lifecycle("init",d)
  assert_eq(count_kind(d,"Off"),1,"one recovery Off")
  assert_eq(d.fields["timed_recovery_required:main"],false,"flag cleared after queued Off")
end)

test("driverSwitched performs standard reads only", function()
  local d=new_device(); lifecycle("driverSwitched",d)
  assert_eq(count_kind(d,"Off"),0,"no unsolicited Off")
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),0,"no private burst")
  assert_true(count_kind(d,"read") >= 3,"standard reads")
end)

test("DUO Open closes opposite channel then queues requested On", function()
  local d=new_device(); d.profile={name="sonoff-hydro-duo"}; d.model="SWV-ZF2"
  command("valve","open",d,{component="channel2",args={}})
  assert_eq(d.attempted[1].kind,"Off","opposite Off")
  assert_eq(d.attempted[1].component,"main","opposite endpoint")
  assert_eq(d.attempted[2].kind,"On","requested On")
  assert_eq(d.attempted[2].component,"channel2","requested endpoint")
end)

test("DUO opposite-channel Off failure cannot suppress requested On", function()
  local d=new_device(); d.profile={name="sonoff-hydro-duo"}; d.model="SWV-ZF2"; d.fail_off=true
  command("valve","open",d,{component="channel2",args={}})
  assert_eq(count_kind(d,"On"),1,"requested On still attempted")
end)

test("manualDuration preference starts only an optional private read", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),1,"fresh read")
  assert_eq(count_kind(d,"On"),0,"no On")
  assert_eq(count_kind(d,"Off"),0,"no Off")
  assert_eq(d.fields.manual_sync_phase,"read","sync phase")
end)

test("explicitly selecting the default 10-minute limit still synchronizes", function()
  local d=new_device(); d.preferences.manualDuration=10
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=20}}})
  assert_eq(d.fields.manual_duration_user_configured,true,"explicit marker")
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),1,"fresh read")
end)

test("unsolicited 0x501D report cannot authorize a write", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  settings_report(d,{0,0,10,0,5,0,10,1,0,0,0,10})
  assert_eq(count_kind(d,"privateWrite"),0,"report does not write")
end)

test("matching 0x501D readback verifies without rewriting", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  settings_read_response(d,{0,0,20,0,20,0,10,1,0,0,0,20})
  assert_eq(count_kind(d,"privateWrite"),0,"no unnecessary write")
  assert_eq(d.fields.manual_default_last_sync_status,"verified","verified from readback")
  assert_eq(d.fields.manual_default_confirmed_duration,20,"confirmed duration")
end)

test("fresh 0x501D read updates duration and fail-safe on full model", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  local source={0,0,10,0x12,0x34,0x56,0x78,1,0x09,0xAB,0,10}
  settings_read_response(d,source)
  local write
  for _,msg in ipairs(d.attempted) do if msg.kind=="privateWrite" then write=msg end end
  assert_true(write~=nil,"write emitted")
  assert_eq(write.value.bytes[2],0,"total duration high")
  assert_eq(write.value.bytes[3],20,"total duration low")
  assert_eq(write.value.bytes[4],0,"irrigation duration high")
  assert_eq(write.value.bytes[5],20,"irrigation duration low")
  for _,i in ipairs({1,6,7,8,9,10}) do assert_eq(write.value.bytes[i],source[i],"preserve byte "..i) end
  assert_eq(write.value.bytes[11],0,"fail-safe high")
  assert_eq(write.value.bytes[12],20,"fail-safe low")
  assert_eq(d.fields.manual_sync_phase,"verify_wait","waiting for delayed verification")
end)

test("Lite 0x501D write updates duration but preserves remaining bytes", function()
  local d=new_device(); d.profile={name="sonoff-hydro-one-lite"}; d.model="SWV-ZNE"; d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  local source={0,0,10,0x12,0x34,0x56,0x78,1,0x09,0xAB,0,10}
  settings_read_response(d,source)
  local write
  for _,msg in ipairs(d.attempted) do if msg.kind=="privateWrite" then write=msg end end
  assert_true(write~=nil,"write emitted")
  assert_eq(write.value.bytes[2],0,"total duration high")
  assert_eq(write.value.bytes[3],20,"total duration low")
  assert_eq(write.value.bytes[4],0,"irrigation duration high")
  assert_eq(write.value.bytes[5],20,"irrigation duration low")
  for _,i in ipairs({1,6,7,8,9,10,11,12}) do assert_eq(write.value.bytes[i],source[i],"preserve byte "..i) end
end)

test("early stale readback during commit delay is ignored", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  settings_read_response(d,{0,0,10,0,5,0,10,1,0,0,0,10})
  settings_report(d,{0,0,10,0,5,0,10,1,0,0,0,10})
  assert_eq(d.fields.manual_sync_phase,"verify_wait","still waiting")
  local verify=last_timer(d,2); assert_true(verify~=nil,"verify timer")
  verify.callback()
  assert_eq(d.fields.manual_sync_phase,"verify","verification requested")
  settings_read_response(d,{0,0,20,0,20,0,10,1,0,0,0,20})
  assert_eq(d.fields.manual_sync_phase,nil,"sync completed")
  assert_eq(d.fields.manual_default_last_sync_status,"verified","verified")
end)

test("full model verification requires matching fail-safe", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  settings_read_response(d,{0,0,10,0,5,0,10,1,0,0,0,10})
  last_timer(d,2).callback()
  settings_read_response(d,{0,0,20,0,20,0,10,1,0,0,0,10})
  assert_eq(d.fields.manual_default_last_sync_status,"failed","short fail-safe rejected")
end)

test("full model verification requires both duration fields", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  settings_read_response(d,{0,0,10,0,10,0,10,1,0,0,0,10})
  last_timer(d,2).callback()
  settings_read_response(d,{0,0,20,0,10,0,10,1,0,0,0,20})
  assert_eq(d.fields.manual_default_last_sync_status,"failed","second duration mismatch rejected")
end)

test("basic Open remains immediate while optional sync is pending", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  command("valve","open",d)
  assert_eq(d.attempted[2].kind,"On","On after independent private read")
end)

test("firmware compact version enables 0x5021 only at 1.1.0", function()
  local d=new_device()
  template.zigbee_handlers.attr[Basic.ID][Basic.attributes.SWBuildID.ID](nil,d,"1.08",{})
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_UNIT_OF_WATER_FLOW),0,"1.0.8")
  template.zigbee_handlers.attr[Basic.ID][Basic.attributes.SWBuildID.ID](nil,d,"1.10",{})
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_UNIT_OF_WATER_FLOW),1,"1.1.0")
end)

test("corrected DUO channel-2 shortage bit is recognized", function()
  local d=new_device(); d.profile={name="sonoff-hydro-duo"}; d.model="SWV-ZF2"
  private_record(d,global_commands.ReportAttribute.ID,utils.ATTR_VALVE_ABNORMAL_STATE,0x08,1)
  assert_true(event_contains(d,"detected"),"shortage detected")
end)


test("refresh retains standard and private telemetry reads", function()
  local d=new_device()
  command("refresh","refresh",d)
  assert_true(count_kind(d,"read") >= 3,"standard reads")
  assert_true(count_private_attr(d,"privateReadMfg",utils.ATTR_CHILD_LOCK) >= 1,"child-lock read")
  assert_true(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS) >= 1,"manual-settings standard read")
end)

test("configured limit still synchronizes when general private Refresh reads are disabled", function()
  local d=new_device(); d.preferences.manualDuration=20; d.preferences.readPrivateOnRefresh=false
  command("refresh","refresh",d)
  assert_eq(count_private_attr(d,"privateRead",utils.ATTR_MANUAL_DEFAULT_SETTINGS),1,"single limit read")
  assert_eq(count_private_attr(d,"privateReadMfg",utils.ATTR_CHILD_LOCK),0,"no general private read burst")
end)

test("child-lock preference still queues its manufacturer-specific write", function()
  local d=new_device(); d.preferences.childLock="locked"
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={childLock="unlocked"}}})
  assert_true(#d.attempted >= 1,"write attempted")
  assert_true(d.attempted[1].kind == "custom_write_attribute" or d.attempted[1].kind == "privateWriteMfg","child lock write path")
end)

test("alarm preference retains read-modify-write workflow", function()
  local d=new_device(); d.preferences.shortageAlarm="enabled"
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={shortageAlarm="disabled"}}})
  assert_true(count_private_attr(d,"privateReadMfg",utils.ATTR_VALVE_ALARM_SETTINGS) >= 1,"alarm settings read")
  alarm_read_response(d,{0,1,1,5})
  local wrote=false
  for _,msg in ipairs(d.attempted) do
    if msg.kind == "privateWriteMfg" or msg.kind == "custom_write_attribute_data" then wrote=true end
  end
  assert_true(wrote,"alarm settings write")
end)

test("OnOff reports still synchronize Valve and Switch states", function()
  local d=new_device()
  onoff_report(d,1,1)
  assert_true(event_contains(d,"open"),"valve open event")
  assert_true(event_contains(d,"on"),"switch on event")
  onoff_report(d,0,1)
  assert_true(event_contains(d,"closed"),"valve closed event")
  assert_true(event_contains(d,"off"),"switch off event")
end)

test("full-model irrigation volume report remains exposed", function()
  local d=new_device()
  private_record(d,global_commands.ReportAttribute.ID,utils.ATTR_REAL_TIME_IRRIGATION_VOLUME,13,1)
  assert_true(event_contains(d,"13"),"volume event")
end)

test("DUO endpoint 2 reports map to channel2", function()
  local d=new_device(); d.profile={name="sonoff-hydro-duo"}; d.model="SWV-ZF2"
  onoff_report(d,1,2)
  local found=false
  for _,evt in ipairs(d.events) do if type(evt)=="table" and evt.endpoint==2 then found=true end end
  assert_true(found,"endpoint 2 event")
end)

test("optional 0x501D failure never blocks a later standard Open", function()
  local d=new_device(); d.preferences.manualDuration=20
  lifecycle("infoChanged",d,nil,{old_st_store={preferences={manualDuration=10}}})
  settings_read_response(d,{1,0,0,0,0,0,0,1,0,1,0,10})
  assert_eq(d.fields.manual_default_last_sync_status,"failed","sync failed")
  command("valve","open",d)
  assert_eq(count_kind(d,"On"),1,"Open still works")
end)

print(string.format("All %d alpha29 runtime scenarios passed.", passed))
