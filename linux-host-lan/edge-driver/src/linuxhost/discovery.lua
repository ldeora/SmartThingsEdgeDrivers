local mdns = require "st.mdns"
local log = require "log"
local API = require "linuxhost.api"
local C = require "linuxhost.constants"
local U = require "linuxhost.util"
local manual_hosts = require "linuxhost.manual_hosts"
local M = {}
local pending = {}
local function select_host(info)
  if type(info)~="table" then return nil end
  local ip=U.trim(info.address)
  if U.is_ipv4(ip) then return ip end
  -- SmartThings socket.http does not necessarily resolve mDNS .local hostnames
  -- through ordinary DNS. Avoid trying a hostname from an IPv6-only record.
  -- Manual host overrides remain available for environments needing DNS.
  return nil
end
local function matches_service(item)
  local si=item and item.service_info
  if type(si)~="table" then return true end
  local name,typ=si.name,si.service_type
  return name==C.MDNS_SERVICE_TYPE or typ==C.MDNS_SERVICE_TYPE
    or (type(name)=="string" and name:find(C.MDNS_SERVICE_TYPE,1,true)~=nil)
end
function M.candidates()
  local items,seen={},{}
  local response,err=mdns.discover(C.MDNS_SERVICE_TYPE,C.MDNS_DOMAIN)
  if not response then log.warn("Linux Host mDNS query failed: "..tostring(err)) end
  local found=response and (response.found or response) or {}
  if type(found)=="table" then
    for _,item in pairs(found) do
      if type(item)=="table" and matches_service(item) and type(item.host_info)=="table" then
        local host=select_host(item.host_info)
        local port=tonumber(item.host_info.port) or C.DEFAULT_PORT
        if U.nonempty(host) and port>0 and port<65536 then
          local key=host..":"..tostring(port)
          if not seen[key] then
            seen[key]=true
            table.insert(items,{host=host,port=port,source="mdns"})
          end
        end
      end
    end
  end
  table.sort(items,function(a,b)
    if U.is_ipv4(a.host) ~= U.is_ipv4(b.host) then return U.is_ipv4(a.host) end
    return a.host<b.host
  end)
  for _,entry in ipairs(manual_hosts) do
    local h,p=U.parse_host_port(entry,C.DEFAULT_PORT)
    if U.nonempty(h) then
      local key=h..":"..tostring(p)
      if not seen[key] then seen[key]=true; table.insert(items,{host=h,port=p,source="manual"}) end
    end
  end
  log.info(string.format("Linux Host discovery: %d candidate(s)",#items))
  return items
end
function M.save_fields(device,host,port,id,name,info)
  if host then device:set_field(C.FIELD_HOST,host,{persist=true}) end
  if port then device:set_field(C.FIELD_PORT,tonumber(port),{persist=true}) end
  if id then device:set_field(C.FIELD_UUID,id,{persist=true}) end
  if name then device:set_field(C.FIELD_NAME,name,{persist=true}) end
  if info then
    -- Keep only valid metadata. Losing this field makes WOL impossible once
    -- the host is off, so write it persistently and log when first acquired.
    if U.valid_wol_mac(info.wol_mac) then
      local new_mac=info.wol_mac:lower()
      if device:get_field(C.FIELD_MAC)~=new_mac then
        device:set_field(C.FIELD_MAC,new_mac,{persist=true})
        log.info("Linux Host WOL MAC saved for "..tostring(device.label or id or "device")..": "..new_mac)
      end
    elseif info.wol_mac~=nil then
      log.warn("Linux Host agent reported invalid WOL MAC; ignoring it")
    end
    if U.is_ipv4(info.wol_broadcast) then
      if device:get_field(C.FIELD_BROADCAST)~=info.wol_broadcast then
        device:set_field(C.FIELD_BROADCAST,info.wol_broadcast,{persist=true})
      end
    end
    if type(info.power_actions)=="table" then
      device:set_field(C.FIELD_POWER_ACTIONS,table.concat(info.power_actions,","),{persist=true})
    end
  end
end
-- Read fresh host metadata for a *known* device, never accepting a MAC
-- supplied by a different UUID at the same IP (e.g. DHCP reassignment).
function M.refresh_fields(device,host,port)
  if not U.nonempty(host) then return nil,"host address is unknown" end
  local info,err=API.fetch_info(host,port)
  if not info then return nil,err end
  local wanted=U.uuid_from_dni(device.device_network_id)
  if not wanted or info.id~=wanted then return nil,"installation ID mismatch in /v1/info" end
  M.save_fields(device,host,port,info.id,info.hostname,info)
  return info,nil
end
function M.apply_pending(device)
  local data=pending[device.device_network_id]
  if not data then return false end
  M.save_fields(device,data.host,data.port,data.id,data.hostname,data.info)
  pending[device.device_network_id]=nil
  return true
end
function M.process_candidate(driver,c)
  local info,err=API.fetch_info(c.host,c.port)
  if not info then return nil,err end
  local dni=U.dni(info.id)
  local existing=U.find_device(driver,dni)
  if existing then
    M.save_fields(existing,c.host,c.port,info.id,info.hostname,info)
    if U.debug(existing) then log.info("Linux Host address updated for "..dni) end
    return existing,nil
  end
  if pending[dni] then return nil,nil end
  local hostname=tostring(info.hostname or "Computer"):sub(1,80)
  local label="Linux "..hostname
  pending[dni]={host=c.host,port=c.port,id=info.id,hostname=hostname,info=info}
  local ok,creation_err=pcall(function()
    driver:try_create_device({type="LAN",device_network_id=dni,label=label,
      profile=C.PROFILE_NAME,manufacturer="Linux Host Agent",
      model="Linux Computer",vendor_provided_label=label,external_id=info.id})
  end)
  if not ok then pending[dni]=nil; return nil,"device creation failed: "..tostring(creation_err) end
  log.info(string.format("Requested Linux Host creation id=%s addr=%s:%d",info.id,c.host,c.port))
  return nil,nil
end
function M.handle_discovery(driver,_,should_continue)
  log.info("Starting Linux Host LAN discovery")
  for _,c in ipairs(M.candidates()) do
    if should_continue and should_continue()==false then return end
    local _,err=M.process_candidate(driver,c)
    if err then log.warn(string.format("Rejecting candidate %s:%s: %s",tostring(c.host),tostring(c.port),tostring(err))) end
  end
end
function M.rediscover(driver,device)
  local wanted=device:get_field(C.FIELD_UUID) or U.uuid_from_dni(device.device_network_id)
  if not wanted then return false,"missing installation UUID" end
  for _,c in ipairs(M.candidates()) do
    local info=API.fetch_info(c.host,c.port)
    if info and info.id==wanted then
      M.save_fields(device,c.host,c.port,info.id,info.hostname,info)
      log.info("Linux Host rediscovered at "..c.host..":"..c.port)
      return true,nil
    end
  end
  return false,"matching Linux Host Agent not found"
end
return M
