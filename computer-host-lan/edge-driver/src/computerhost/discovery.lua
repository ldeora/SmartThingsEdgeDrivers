local mdns = require "st.mdns"
local log = require "log"
local API = require "computerhost.api"
local C = require "computerhost.constants"
local U = require "computerhost.util"
local manual_hosts = require "computerhost.manual_hosts"
local M = {}
local pending = {}
-- A silently dropped create request must not block all subsequent scans.
-- Keep this longer than a typical hub add/init callback, but retry eventually.
local PENDING_CREATE_TTL_SECONDS = 120
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
  if not response then log.warn("Computer Host mDNS query failed: "..tostring(err)) end
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
  log.info(string.format("Computer Host discovery: %d candidate(s)",#items))
  return items
end
function M.save_fields(device,host,port,id,name,info)
  local override=U.host_override(device)
  if not override then
    if host then device:set_field(C.FIELD_HOST,host,{persist=true}) end
    if port then device:set_field(C.FIELD_PORT,tonumber(port),{persist=true}) end
  end
  if id then device:set_field(C.FIELD_UUID,id,{persist=true}) end
  local confirmed=override or not device:get_field(C.FIELD_ENDPOINT_UNCONFIRMED)
  if name and confirmed then device:set_field(C.FIELD_NAME,name,{persist=true}) end
  if info and confirmed then
    if C.PLATFORMS[info.platform] then
      device:set_field(C.FIELD_PLATFORM,info.platform,{persist=true})
    end
    -- Keep only valid metadata. Losing this field makes WOL impossible once
    -- the host is off, so write it persistently and log when first acquired.
    if U.valid_wol_mac(info.wol_mac) then
      local new_mac=info.wol_mac:lower()
      if device:get_field(C.FIELD_MAC)~=new_mac then
        device:set_field(C.FIELD_MAC,new_mac,{persist=true})
        log.info("Computer Host WOL MAC saved (address omitted)")
      end
    elseif info.wol_mac~=nil then
      log.warn("Computer Host agent reported invalid WOL MAC; ignoring it")
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
local function stored_address(device)
  return device:get_field(C.FIELD_HOST),device:get_field(C.FIELD_PORT) or C.DEFAULT_PORT
end
local function effective_address(device)
  local host,port=stored_address(device)
  local override=U.host_override(device)
  if override then return U.parse_host_port(override,port) end
  return host,port
end
local function same_address(a,ap,b,bp)
  return a==b and tonumber(ap)==tonumber(bp)
end
local function metadata_allowed(device,host,port)
  local current,current_port=effective_address(device)
  return same_address(host,port,current,current_port)
    and (U.host_override(device) or not device:get_field(C.FIELD_ENDPOINT_UNCONFIRMED))
end
-- Read fresh metadata only from the current effective endpoint. A migration
-- is not metadata evidence until a normal health poll confirms the UUID.
function M.refresh_fields(device,host,port)
  if not U.nonempty(host) then return nil,"host address is unknown" end
  if not metadata_allowed(device,host,port) then return nil,"endpoint not confirmed or changed" end
  local info,err=API.fetch_info(host,port)
  if not info then return nil,err end
  local wanted=U.uuid_from_dni(device.device_network_id)
  if not wanted or info.id~=wanted then return nil,"installation ID mismatch in /v2/info" end
  if not metadata_allowed(device,host,port) then return nil,"endpoint not confirmed or changed" end
  M.save_fields(device,host,port,info.id,info.hostname,info)
  return info,nil
end

-- Discovery runs outside the device poll thread. Do not move an endpoint
-- under an in-flight poll/metrics/power callback; after a yielding probe, check
-- that the address, override and health success counter still agree.
local function busy(device)
  return device:get_field(C.FIELD_IN_PROGRESS) or device:get_field(C.FIELD_METRICS_BUSY)
    or device:get_field(C.FIELD_POWER_BUSY)
end
local function snapshot(device)
  local host,port=stored_address(device)
  return {host=host,port=port,successes=device:get_field("computerhost_success_count"),
    unconfirmed=device:get_field(C.FIELD_ENDPOINT_UNCONFIRMED)}
end
local function unchanged(device,before,from_poll)
  local host,port=stored_address(device)
  return not U.host_override(device)
    and not device:get_field(C.FIELD_POWER_BUSY)
    and (from_poll or not busy(device))
    and same_address(host,port,before.host,before.port)
    and device:get_field("computerhost_success_count")==before.successes
    and device:get_field(C.FIELD_ENDPOINT_UNCONFIRMED)==before.unconfirmed
end
local function responsive(before,wanted)
  if not U.nonempty(before.host) then return false end
  local health=API.fetch_health(before.host,before.port)
  return health~=nil and health.id==wanted
end
local function relocate(device,before,c,from_poll)
  if not unchanged(device,before,from_poll) then return false end
  -- Persist the guard before the new address, including across driver restart.
  -- Do not copy discovery metadata (MAC, broadcast, platform or power actions).
  device:set_field(C.FIELD_ENDPOINT_UNCONFIRMED,true,{persist=true})
  device:set_field(C.FIELD_LAST_OK,false)
  M.save_fields(device,c.host,c.port)
  log.info("Computer Host discovered endpoint changed; awaiting health confirmation (network addresses omitted)")
  return true
end
function M.apply_pending(device)
  local data=pending[device.device_network_id]
  if not data then return false end
  pending[device.device_network_id]=nil
  -- A late creation callback must not overwrite an established/manual endpoint.
  if U.host_override(device) or U.nonempty(device:get_field(C.FIELD_HOST)) then return false end
  M.save_fields(device,data.host,data.port,data.id,data.hostname,data.info)
  return true
end
function M.process_candidate(driver,c)
  local info,err=API.fetch_info(c.host,c.port)
  if not info then return nil,err end
  local dni=U.dni(info.id)
  local existing=U.find_device(driver,dni)
  if existing then
    if U.host_override(existing) or busy(existing) then return existing,nil end
    local before=snapshot(existing)
    if same_address(c.host,c.port,before.host,before.port) then
      M.save_fields(existing,c.host,c.port,info.id,info.hostname,info)
    elseif not responsive(before,info.id) then
      relocate(existing,before,c,false)
    end
    return existing,nil
  end
  local queued=pending[dni]
  if queued then
    local age=os.time()-(tonumber(queued.at) or 0)
    if age>=0 and age<PENDING_CREATE_TTL_SECONDS then return nil,nil end
    -- A previous request never completed (or the runtime clock changed).
    -- Retry with current verified metadata; late callbacks use the same DNI.
    log.warn("Computer Host creation still unconfirmed; retrying on next scan")
    pending[dni]=nil
  end
  local hostname=tostring(info.hostname or "Computer"):sub(1,80)
  local label=(info.platform == "windows" and "Windows " or "Linux ")..hostname
  pending[dni]={host=c.host,port=c.port,id=info.id,hostname=hostname,info=info,at=os.time()}
  local ok,creation_err=pcall(function()
    driver:try_create_device({type="LAN",device_network_id=dni,label=label,
      profile=C.profile_for(info.platform),manufacturer="Computer Host Agent",
      model=(info.platform == "windows" and "Windows Computer" or "Linux Computer"),
      vendor_provided_label=label,external_id=info.id})
  end)
  if not ok then pending[dni]=nil; return nil,"device creation failed: "..tostring(creation_err) end
  log.info("Requested Computer Host device creation after verified protocol/UUID")
  return nil,nil
end
function M.handle_discovery(driver,_,should_continue)
  log.info("Starting Computer Host LAN discovery")
  for _,c in ipairs(M.candidates()) do
    if should_continue and should_continue()==false then return end
    local _,err=M.process_candidate(driver,c)
    if err then log.warn(string.format("Rejecting candidate %s:%s: %s",tostring(c.host),tostring(c.port),tostring(err))) end
  end
end
function M.rediscover(driver,device)
  if U.host_override(device) then return false,"manual host override active" end
  local wanted=U.uuid_from_dni(device.device_network_id)
  if not wanted then return false,"missing installation UUID" end
  -- Called by the device poll itself, so its own busy flag is expected.
  local before=snapshot(device)
  local healthy=responsive(before,wanted)
  if not unchanged(device,before,true) then return false,"endpoint changed during rediscovery" end
  if healthy then return true,nil end
  for _,c in ipairs(M.candidates()) do
    if not unchanged(device,before,true) then return false,"endpoint changed during rediscovery" end
    if not same_address(c.host,c.port,before.host,before.port) then
      local info=API.fetch_info(c.host,c.port)
      if info and info.id==wanted then
        if relocate(device,before,c,true) then return true,nil end
        return false,"endpoint changed during rediscovery"
      end
    end
  end
  return false,"matching Computer Host Agent not found"
end
return M
