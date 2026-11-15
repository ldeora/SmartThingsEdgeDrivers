local caps=require "st.capabilities"
local log=require "log"
local C=require "linuxhost.constants"
local M={}

local custom={
  hostStatus={id=C.NAMESPACE..".linuxHostStatus"},
  cpu={id=C.NAMESPACE..".linuxCpuUsage"},
  memory={id=C.NAMESPACE..".linuxMemoryUsage"},
  disk={id=C.NAMESPACE..".linuxDiskUsage"},
  uptime={id=C.NAMESPACE..".linuxUptime"},
  load={id=C.NAMESPACE..".linuxLoad"},
}

local function supports(device,id)
  if type(device.supports_capability_by_id)=="function" then
    local ok,result=pcall(device.supports_capability_by_id,device,id,"main")
    if ok then return result==true end
  end
  local main=device.profile and device.profile.components and device.profile.components.main
  local listed=main and main.capabilities
  if type(listed)~="table" then return false end
  for _,cap in pairs(listed) do
    if cap==id or (type(cap)=="table" and (cap.id==id or cap.ID==id)) then return true end
  end
  return false
end

local QUIET={visibility={displayed=false}}

local function emit(device,key,attribute,value,quiet)
  local def=custom[key]
  if not def or not supports(device,def.id) then return false end
  local ok,err=pcall(function()
    local capability=caps[def.id]
    -- Edge capability attributes are callable tables (via __call), not only
    -- ordinary functions. A type(... ) == "function" check silently rejects
    -- legitimate custom capabilities and prevents their initial state events.
    if type(capability) ~= "table" then
      error("custom capability unavailable in hub registry: "..def.id)
    end
    local constructor=capability[attribute]
    if constructor == nil then
      error("custom capability attribute unavailable: "..def.id.."."..attribute)
    end
    -- Calling through pcall also reports genuinely missing/non-callable
    -- attributes without misclassifying the Edge library's callable tables.
    local event
    if quiet then event=constructor(value,QUIET)
    else event=constructor(value) end
    device:emit_event(event)
  end)
  if not ok then
    log.warn("Linux Host custom telemetry event error: "..tostring(err))
    return false
  end
  return true
end

local function finite_number(value)
  return type(value)=="number" and value==value and value~=math.huge and value~=-math.huge
end

local function uptime_text(seconds)
  if not finite_number(seconds) or seconds<0 then return nil end
  local total_minutes=math.floor(seconds/60)
  local days=math.floor(total_minutes/1440)
  local hours=math.floor((total_minutes%1440)/60)
  local minutes=total_minutes%60
  if days>0 then
    return hours>0 and string.format("%dd %dh",days,hours) or string.format("%dd",days)
  elseif hours>0 then
    return minutes>0 and string.format("%dh %dm",hours,minutes) or string.format("%dh",hours)
  end
  return string.format("%dm",minutes)
end

function M.custom_event(device,key,attribute,value,quiet)
  return emit(device,key,attribute,value,quiet)
end

function M.status(device,status)
  return emit(device,"hostStatus","status",status,false)
end

function M.metrics(device,metrics)
  if type(metrics)~="table" then return end
  local recent=device:get_field(C.FIELD_LAST_METRICS) or {}
  local function changed(key,value,step,callback,minimum,maximum)
    if not finite_number(value) then return end
    if minimum and value<minimum then return end
    if maximum and value>maximum then return end
    local old=recent[key]
    if old==nil or math.abs(value-old)>=step then
      -- Do not remember failed emissions. This is particularly important for
      -- unchanged totals such as installed RAM: retry on the next poll after
      -- the hub capability registry becomes available.
      local sent=callback(value)
      if sent ~= false then recent[key]=value end
    end
  end

  -- Standard capability: keep CPU temperature available to every profile.
  changed("cpu_temperature_c",metrics.cpu_temperature_c,0.5,function(value)
    device:emit_event(caps.temperatureMeasurement.temperature({value=value,unit="C"}))
  end,-40,150)

  -- Custom monitoring attributes are hidden from event history to avoid
  -- creating a high-volume history stream while keeping the latest state.
  changed("cpu_usage_percent",metrics.cpu_usage_percent,1,function(value)
    return emit(device,"cpu","cpuUsage",value,true)
  end,0,100)
  changed("memory_usage_percent",metrics.memory_usage_percent,0.5,function(value)
    return emit(device,"memory","memoryUsage",value,true)
  end,0,100)
  changed("memory_total_gib",finite_number(metrics.memory_total_bytes)
      and metrics.memory_total_bytes/1073741824 or nil,0.1,function(value)
    return emit(device,"memory","memoryTotalGiB",math.floor(value*10+0.5)/10,true)
  end,0,1048576)
  changed("disk_root_usage_percent",metrics.disk_root_usage_percent,0.5,function(value)
    return emit(device,"disk","diskUsage",value,true)
  end,0,100)

  changed("load_1m",metrics.load_1m,0.05,function(value)
    return emit(device,"load","loadOne",value,true)
  end,0,1000000)
  changed("load_5m",metrics.load_5m,0.05,function(value)
    return emit(device,"load","loadFive",value,true)
  end,0,1000000)
  changed("load_15m",metrics.load_15m,0.05,function(value)
    return emit(device,"load","loadFifteen",value,true)
  end,0,1000000)

  local minutes=finite_number(metrics.uptime_seconds) and math.floor(metrics.uptime_seconds/60) or nil
  changed("uptime_minutes",minutes,5,function(value)
    return emit(device,"uptime","uptimeMinutes",value,true)
  end,0,100000000)
  local readable=uptime_text(metrics.uptime_seconds)
  if readable and recent.uptime_text~=readable then
    if emit(device,"uptime","uptimeText",readable,true) then
      recent.uptime_text=readable
    end
  end

  device:set_field(C.FIELD_LAST_METRICS,recent)
end

return M
