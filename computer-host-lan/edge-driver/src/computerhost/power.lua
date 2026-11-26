local log=require "log"
local API=require "computerhost.api"
local C=require "computerhost.constants"
local U=require "computerhost.util"
local WOL=require "computerhost.wol"
local Discovery=require "computerhost.discovery"
local M={}
local function address(device)
  local override=U.host_override(device)
  if override then return U.parse_host_port(override,device:get_field(C.FIELD_PORT) or C.DEFAULT_PORT) end
  return device:get_field(C.FIELD_HOST),device:get_field(C.FIELD_PORT) or C.DEFAULT_PORT
end
function M.wake(device)
  local mac=U.wol_mac(device)
  -- After device recreation or driver updates, persistent WOL metadata can
  -- be temporarily unavailable. Recover it from the already-identified agent
  -- *while the host is running* rather than requiring users to re-pair.
  if not U.valid_wol_mac(mac) then
    local override=device.preferences and device.preferences.wolMacOverride
    if U.nonempty(override) then
      return false,"WOL MAC override is invalid; expected 6-byte Ethernet MAC"
    end
    local host,port=address(device)
    if host then
      local info,refresh_err=Discovery.refresh_fields(device,host,port)
      if not info then
        log.warn("Computer Host WOL metadata recovery failed: "..tostring(refresh_err))
      end
      mac=U.wol_mac(device)
    end
  end
  if not U.valid_wol_mac(mac) then
    return false,"WOL MAC unavailable: reconnect the running computer agent or configure WOL MAC override"
  end
  local broadcast=U.wol_broadcast(device)
  local ok,err=WOL.send(mac,broadcast,U.wol_port(device))
  if not ok then
    log.error("Computer Host WOL not sent: "..tostring(err))
    return false,err
  end
  device:set_field(C.FIELD_PENDING_ACTION,"wake",{persist=true})
  device:set_field(C.FIELD_PENDING_AT,os.time(),{persist=true})
  log.info("Computer Host magic packet sent (network identifiers omitted)")
  return true
end
function M.action(device,action)
  if device:get_field(C.FIELD_ENDPOINT_UNCONFIRMED) and not U.host_override(device) then
    return false,"discovered endpoint not yet confirmed by health polling"
  end
  if not U.boolean_pref(device,"allowPowerCommands") then
    return false,"power commands disabled in device settings"
  end
  local key=U.key(device)
  if not key then return false,"missing/invalid 64-character control key" end
  local declared=device:get_field(C.FIELD_POWER_ACTIONS)
  if type(declared)=="string" and not declared:find(action,1,true) then
    return false,"agent does not advertise power control: "..action
  end
  local host,port=address(device)
  if not host then return false,"unknown agent address" end
  local uuid=U.uuid_from_dni(device.device_network_id)
  local ok,err,status=API.control(host,port,uuid,key,action)
  if not ok then return false,err,status end
  device:set_field(C.FIELD_PENDING_ACTION,action,{persist=true})
  device:set_field(C.FIELD_PENDING_AT,os.time(),{persist=true})
  log.info("Computer Host accepted "..action.." command for "..tostring(device.label))
  return true
end
return M
