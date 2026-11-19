local Driver=require "st.driver"
local caps=require "st.capabilities"
local log=require "log"
local API=require "computerhost.api"
local C=require "computerhost.constants"
local D=require "computerhost.discovery"
local U=require "computerhost.util"
local Telemetry=require "computerhost.telemetry"
local Power=require "computerhost.power"
local Presence=require "computerhost.presence"
local State=require "computerhost.state"

local template={}
local poll,metrics_poll,schedule_poll,schedule_metrics

local function switch_state(device,new_state,force)
  local old=device:get_field(C.FIELD_LAST_SWITCH)
  -- Always publish the first observed state after a driver restart. The stored
  -- local state is not proof the platform has received an attribute event.
  local published=device:get_field(C.FIELD_SWITCH_PUBLISHED)
  if old==new_state and not force and published then return end
  device:set_field(C.FIELD_LAST_SWITCH,new_state,{persist=true})
  device:set_field(C.FIELD_SWITCH_PUBLISHED,true)
  device:emit_event(caps.switch.switch(new_state))
  log.info(string.format("Computer Host %s switch -> %s",tostring(device.label),new_state))
end

local function host_status(device,new_status)
  if not new_status then return end
  -- Publish once after driver initialization even when a previously stored
  -- value is equal. Do not cache failed custom event emissions.
  if device:get_field(C.FIELD_LAST_STATUS)==new_status
      and device:get_field(C.FIELD_STATUS_PUBLISHED) then return end
  if Telemetry.status(device,new_status) then
    device:set_field(C.FIELD_LAST_STATUS,new_status,{persist=true})
    device:set_field(C.FIELD_STATUS_PUBLISHED,true)
  end
end

local function get_address(device)
  local override=U.host_override(device)
  if override then return U.parse_host_port(override,device:get_field(C.FIELD_PORT) or C.DEFAULT_PORT) end
  return device:get_field(C.FIELD_HOST),device:get_field(C.FIELD_PORT) or C.DEFAULT_PORT
end

local function cancel(device,key)
  local old=device:get_field(key)
  if old then pcall(function() device.thread:cancel_timer(old) end) end
  device:set_field(key,nil)
end

local function pending(device)
  local action=device:get_field(C.FIELD_PENDING_ACTION)
  if action then
    local raw_started=device:get_field(C.FIELD_PENDING_AT)
    local started=tonumber(raw_started) or 0
    if os.time()-started>180 then
      log.warn("Computer Host pending "..tostring(action).." expired without confirmation")
      device:set_field(C.FIELD_PENDING_ACTION,nil,{persist=true})
      device:set_field(C.FIELD_PENDING_AT,nil,{persist=true})
      action=nil
    end
  end
  return action
end

local function clear_pending(device)
  device:set_field(C.FIELD_PENDING_ACTION,nil,{persist=true})
  device:set_field(C.FIELD_PENDING_AT,nil,{persist=true})
end

local function failure(driver,device,reason)
  local previous_failures=device:get_field(C.FIELD_FAILURES)
  local n=(tonumber(previous_failures) or 0)+1
  device:set_field(C.FIELD_FAILURES,n)
  device:set_field(C.FIELD_LAST_OK,false)
  local kind=Presence.classify_failure(reason)
  local previous_host_failures=device:get_field(C.FIELD_HOST_FAILURES)
  local host_failures=kind=="host_unreachable" and (tonumber(previous_host_failures) or 0)+1 or 0
  device:set_field(C.FIELD_HOST_FAILURES,host_failures)
  log.warn(string.format("Computer Host %s failed health check #%d (%s; %s)",
    tostring(device.label),n,tostring(reason),kind))
  if n>=U.failure_threshold(device) then
    local action=pending(device)
    local status,new_switch,confirmed=State.failure(action,kind,n,host_failures,
      U.failure_threshold(device),U.assume_off_when_unreachable(device))
    if new_switch then switch_state(device,new_switch) end
    host_status(device,status)
    if confirmed then
      log.info("Computer Host "..tostring(device.label).." inferred "..status..
        " after acknowledged "..tostring(action).." and host timeouts")
      clear_pending(device)
    elseif n==U.failure_threshold(device) and not action then
      log.info("Computer Host "..tostring(device.label).." "..status..
        "; switch state is based on configured network-failure inference")
    end
  end
  if n>=U.failure_threshold(device) and n% C.REDISCOVERY_EVERY_FAILURES==0 and not U.host_override(device) then
    local ok,err=D.rediscover(driver,device)
    if not ok and U.debug(device) then log.info("Computer Host rediscovery: "..tostring(err)) end
  end
end

poll=function(driver,device,reason)
  if device:get_field(C.FIELD_IN_PROGRESS) then return end
  device:set_field(C.FIELD_IN_PROGRESS,true)
  local ok,err=pcall(function()
    local host,port=get_address(device)
    if not host then
      local found,find_err=D.rediscover(driver,device)
      if not found then failure(driver,device,"unknown address: "..tostring(find_err)); return end
      host,port=get_address(device)
    end
    local health,health_err=API.fetch_health(host,port)
    if not health then failure(driver,device,health_err); return end
    if health.id~=U.uuid_from_dni(device.device_network_id) then
      failure(driver,device,"unexpected installation ID at known address")
      return
    end
    local previous_boot=device:get_field(C.FIELD_LAST_BOOT)
    local boot_changed=health.boot_id and previous_boot and health.boot_id~=previous_boot
    if boot_changed then
      log.info("Computer Host boot ID changed: "..tostring(device.label))
    end
    if health.boot_id then device:set_field(C.FIELD_LAST_BOOT,health.boot_id,{persist=true}) end
    D.save_fields(device,U.host_override(device) and nil or host,
      U.host_override(device) and nil or port,health.id)
    local previous_failures=device:get_field(C.FIELD_FAILURES)
    local failed_polls=tonumber(previous_failures) or 0
    device:set_field(C.FIELD_FAILURES,0)
    device:set_field(C.FIELD_HOST_FAILURES,0)
    device:set_field(C.FIELD_LAST_OK,true)
    device:online() -- The hub-side controller stays usable regardless of host state.
    switch_state(device,"on")
    if failed_polls>0 then
      log.info(string.format("Computer Host %s connection restored after %d failed check(s)",
        tostring(device.label),failed_polls))
    end
    local action=pending(device)
    local raw_pending_at=device:get_field(C.FIELD_PENDING_AT)
    local action_age=action and math.max(0,os.time()-(tonumber(raw_pending_at) or os.time())) or 0
    local status,confirmed=State.success(action,boot_changed,failed_polls,action_age)
    host_status(device,status)
    if confirmed then clear_pending(device) end
    -- Edge get_field() may return zero values when an unset field is queried.
    -- Bind its result first so tonumber() always gets one argument.
    local previous_successes=device:get_field("computerhost_success_count")
    local n=(tonumber(previous_successes) or 0)+1
    device:set_field("computerhost_success_count",n)
    if n==1 or n%20==0 or not U.valid_wol_mac(device:get_field(C.FIELD_MAC)) then
      local info,info_err=D.refresh_fields(device,host,port)
      if not info and (n==1 or n%20==0 or U.debug(device)) then
        log.warn("Computer Host metadata refresh failed: "..tostring(info_err))
      elseif info and not U.valid_wol_mac(device:get_field(C.FIELD_MAC)) then
        -- The agent can be healthy with a missing NIC, but WOL needs a MAC.
        log.warn("Computer Host WOL MAC unavailable; set WOL MAC override if needed")
      end
    end
    if U.debug(device) then
      log.debug(string.format("Computer Host health OK: %s (%s:%s, uptime=%s)",
        tostring(reason),tostring(host),tostring(port),tostring(health.uptime_seconds)))
    end
  end)
  device:set_field(C.FIELD_IN_PROGRESS,false)
  -- Lua/runtime defects are not evidence of host/network unavailability.
  -- HTTP failures are counted inside the protected polling body above.
  if not ok then log.error("Computer Host polling exception: "..tostring(err)) end
end

metrics_poll=function(driver,device,reason)
  if device:get_field(C.FIELD_METRICS_BUSY) or not device:get_field(C.FIELD_LAST_OK) then return end
  device:set_field(C.FIELD_METRICS_BUSY,true)
  local ok,err=pcall(function()
    local host,port=get_address(device)
    if not host then return end
    local metrics,request_err=API.fetch_metrics(host,port)
    if not metrics then
      if U.debug(device) then log.warn("Computer Host metrics failed: "..tostring(request_err)) end
      return
    end
    if metrics.id~=U.uuid_from_dni(device.device_network_id) then
      log.error("Computer Host rejected metrics from wrong installation ID")
      return
    end
    Telemetry.metrics(device,metrics)
  end)
  device:set_field(C.FIELD_METRICS_BUSY,false)
  if not ok then log.error("Computer Host telemetry exception: "..tostring(err)) end
end

schedule_poll=function(driver,device,delay)
  cancel(device,C.FIELD_POLL_TIMER)
  local t=device.thread:call_with_delay(delay or U.poll_interval(device),function()
    device:set_field(C.FIELD_POLL_TIMER,nil)
    poll(driver,device,"scheduled")
    local next_delay=pending(device) and 5 or U.poll_interval(device)
    schedule_poll(driver,device,next_delay)
  end,"Computer Host health")
  device:set_field(C.FIELD_POLL_TIMER,t)
end

schedule_metrics=function(driver,device,delay)
  cancel(device,C.FIELD_METRICS_TIMER)
  local t=device.thread:call_with_delay(delay or U.telemetry_interval(device),function()
    device:set_field(C.FIELD_METRICS_TIMER,nil)
    metrics_poll(driver,device,"scheduled")
    schedule_metrics(driver,device,U.telemetry_interval(device))
  end,"Computer Host metrics")
  device:set_field(C.FIELD_METRICS_TIMER,t)
end

local function added(_,device)
  D.apply_pending(device)
  device:set_field(C.FIELD_FAILURES,0)
  device:online()
end
local function ensure_profile(device)
  -- Custom monitoring capabilities must be registered before the advanced
  -- profile is installed. Request the platform-specific profile if custom capabilities are not yet
  -- registered on this account; the platform updates profiles asynchronously.
  local required=C.NAMESPACE..".computerHostStatus"
  local supported=false
  if type(device.supports_capability_by_id)=="function" then
    local ok,result=pcall(device.supports_capability_by_id,device,required,"main")
    supported=ok and result==true
  end
  if supported or device:get_field(C.FIELD_PROFILE_UPDATE_SENT) then return end
  if type(device.try_update_metadata)~="function" then
    log.warn("Computer Host cannot request advanced profile migration on this hub runtime")
    return
  end
  local ok,err=pcall(device.try_update_metadata,device,{profile=C.profile_for(device:get_field(C.FIELD_PLATFORM))})
  if ok then
    device:set_field(C.FIELD_PROFILE_UPDATE_SENT,true)
    log.info("Computer Host requested device profile update to "..C.profile_for(device:get_field(C.FIELD_PLATFORM)))
  else
    log.warn("Computer Host advanced profile migration request failed: "..tostring(err))
  end
end

local function init(driver,device)
  local id=U.uuid_from_dni(device.device_network_id)
  if id then device:set_field(C.FIELD_UUID,id,{persist=true}) end
  -- Apply the newly discovered platform BEFORE selecting a profile.
  -- Windows and Linux advertise the same shared capabilities but differ in
  -- their OS-specific profile content.
  D.apply_pending(device)
  ensure_profile(device)
  device:online()
  device:set_field(C.FIELD_SWITCH_PUBLISHED,false)
  device:set_field(C.FIELD_STATUS_PUBLISHED,false)
  device:set_field(C.FIELD_LAST_OK,false)
  schedule_poll(driver,device,2)
  schedule_metrics(driver,device,8)
end
local function removed(_,device)
  cancel(device,C.FIELD_POLL_TIMER)
  cancel(device,C.FIELD_METRICS_TIMER)
end
local function info_changed(driver,device)
  -- The cloud may have completed a profile update since the previous init.
  -- If it has not, allow one fresh request after this metadata notification.
  device:set_field(C.FIELD_PROFILE_UPDATE_SENT,nil)
  device:set_field(C.FIELD_STATUS_PUBLISHED,false)
  ensure_profile(device)
  -- Avoid secrets in logs; clear the transient metadata refresh counter.
  device:set_field("computerhost_success_count",0)
  schedule_poll(driver,device,1)
  schedule_metrics(driver,device,4)
end
local function refresh(driver,device)
  poll(driver,device,"manual refresh")
  metrics_poll(driver,device,"manual refresh")
end
local function turn_on(driver,device)
  if device:get_field(C.FIELD_LAST_OK) then
    poll(driver,device,"on command: already reachable")
    return
  end
  local ok,err=Power.wake(device)
  if not ok then
    log.error("Computer Host switch ON rejected: "..tostring(err))
    switch_state(device,"off",true) -- undo an optimistic app toggle
    return
  end

  host_status(device,"starting")
  schedule_poll(driver,device,5)
end
local function turn_off(driver,device)
  if not device:get_field(C.FIELD_LAST_OK) then
    log.warn("Computer Host switch OFF not sent: the agent is unreachable")
    -- Do not claim to have shut the computer down; reassert known state.
    local known=device:get_field(C.FIELD_LAST_SWITCH)
    if known then switch_state(device,known,true) end
    return
  end
  local ok,err=Power.action(device,"shutdown")
  if not ok then
    log.error("Computer Host switch OFF rejected: "..tostring(err))
    switch_state(device,"on",true) -- reject optimistic OFF
    return
  end
  host_status(device,"stopping")
  schedule_poll(driver,device,5)
end
local function momentary(driver,device,command)
  local component=command.component or ""
  if component=="wake" then
    local ok,err=Power.wake(device)
    if not ok then log.error("Computer Host Wake rejected: "..tostring(err)); return end
    host_status(device,"starting")
    schedule_poll(driver,device,5)
    return
  end
  local action=(component=="reboot" and "reboot") or (component=="suspend" and "suspend")
  if not action then log.warn("Computer Host unknown momentary component "..tostring(component)); return end
  if not device:get_field(C.FIELD_LAST_OK) then
    log.warn("Computer Host "..action.." not sent: agent unreachable")
    return
  end
  local ok,err=Power.action(device,action)
  if not ok then log.error("Computer Host "..action.." rejected: "..tostring(err)); return end
  host_status(device,action=="reboot" and "rebooting" or "suspending")
  schedule_poll(driver,device,5)
end

template.discovery=D.handle_discovery
template.lifecycle_handlers={added=added,init=init,removed=removed,infoChanged=info_changed}
template.capability_handlers={
  [caps.switch.ID]={
    [caps.switch.commands.on.NAME]=turn_on,
    [caps.switch.commands.off.NAME]=turn_off,
  },
  [caps.refresh.ID]={ [caps.refresh.commands.refresh.NAME]=refresh },
  [caps.momentary.ID]={ [caps.momentary.commands.push.NAME]=momentary },
}
log.info(string.format("Starting %s v%s",C.DRIVER_NAME,C.DRIVER_VERSION))
Driver(C.DRIVER_NAME,template):run()
