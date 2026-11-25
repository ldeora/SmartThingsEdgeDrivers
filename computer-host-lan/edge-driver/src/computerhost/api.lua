local cosock = require "cosock"
local http = cosock.asyncify "socket.http"
local json = require "st.json"
local C = require "computerhost.constants"
local U = require "computerhost.util"
local SHA = require "computerhost.sha256"
local M = {}
local MAX_RESPONSE = 32768

-- LuaSocket's http.open() reapplies this module timeout after the custom
-- create callback, overriding sock:settimeout() there. Set both to the same
-- value so the driver's intended timeout is the effective connect/read limit.
http.TIMEOUT = C.HTTP_TIMEOUT

local DEADLINE_ERROR = "timeout: HTTP request deadline exceeded"

local function request_budget()
  -- Upstream LuaSocket returns epoch seconds, while the SmartThings socket
  -- reference documents epoch milliseconds. Normalize either representation.
  local function now()
    local t=cosock.socket.gettime()
    if type(t)~="number" or t~=t or t==math.huge or t==-math.huge then
      error("invalid HTTP deadline clock")
    end
    return t>=1e11 and t/1000 or t
  end
  local last=now()
  local deadline=last+C.HTTP_TOTAL_DEADLINE
  return function()
    local current=now()
    -- gettime is a wall clock, not a monotonic clock. Do not extend an
    -- in-flight request across a detected backwards clock correction.
    if current<last then deadline=-math.huge end
    last=current
    return deadline-current
  end
end

-- cosock's TCP passthrough can yield repeatedly inside one receive/send.
-- Clamp EVERY readiness wait, not merely the timeout set before a call.
-- Run the HTTP operation in a plain nested coroutine (not cosock.spawn),
-- forwarding its socket.select-compatible yields through the device's own
-- cosock coroutine. No background request remains after an expired wait.
-- See cosock/socket/internals.lua: passthroughbuilder.
local function within_deadline(fn,remaining)
  local task=coroutine.create(fn)
  local args=table.pack()
  while remaining()>0 do
    local result=table.pack(coroutine.resume(task,table.unpack(args,1,args.n)))
    if not result[1] then error(result[2],0) end
    local left=remaining()
    if left<=0 then break end
    if coroutine.status(task)=="dead" then
      return table.unpack(result,2,result.n)
    end
    local reads,writes,wait=result[2],result[3],result[4]
    if (reads~=nil and type(reads)~="table") or
       (writes~=nil and type(writes)~="table") or
       (wait~=nil and type(wait)~="number") then
      error("unexpected cosock HTTP readiness yield")
    end
    if not wait or wait<0 then wait=C.HTTP_TIMEOUT end
    args=table.pack(cosock.socket.select(reads,writes,math.min(wait,C.HTTP_TIMEOUT,left)))
  end
  return nil,DEADLINE_ERROR
end

local function request_json(host,port,path,method,headers)
  local clean_host,clean_port=U.parse_host_port(host,port)
  if not clean_host then return nil,"invalid address" end
  local chunks,size={},0
  local response_code
  local url=string.format("http://%s:%d%s",U.host_for_url(clean_host),clean_port,path)
  local request_headers={
    ["Accept"]="application/json", ["User-Agent"]="SmartThings-ComputerHost/"..C.DRIVER_VERSION,
    ["Connection"]="close"
  }
  for k,v in pairs(headers or {}) do request_headers[k]=v end
  local raw_socket,closed
  local function close_socket()
    if raw_socket and not closed then
      closed=true
      return raw_socket:close()
    end
    return 1
  end
  local ok,success,code,_,status=pcall(function()
    local remaining=request_budget()
    return within_deadline(function()
      return http.request({url=url,method=method or "GET",headers=request_headers,
        -- A host agent never redirects. Keep the request and its credentials
        -- at the selected endpoint, with exactly one owned TCP socket.
        redirect=false,
        sink=function(chunk)
          if remaining()<=0 then return nil,DEADLINE_ERROR end
          if chunk then
            size=size+#chunk
            if size>MAX_RESPONSE then return nil,"response too large" end
            chunks[#chunks+1]=chunk
          end
          return 1
        end,
        create=function()
          if remaining()<=0 then return nil,DEADLINE_ERROR end
          if raw_socket then return nil,"unexpected second HTTP socket" end
          local sock,err=cosock.socket.tcp()
          if not sock then return nil,err end
          raw_socket=sock
          sock:settimeout(C.HTTP_TIMEOUT)
          -- Also check between immediately completing operations, such as
          -- buffered header reads, which do not necessarily yield to cosock.
          local proxy={close=close_socket}
          for _,name in ipairs({"connect","send","receive","settimeout","getfd","dirty"}) do
            proxy[name]=function(_,...)
              if remaining()<=0 then return nil,DEADLINE_ERROR end
              local result=table.pack(sock[name](sock,...))
              if remaining()<=0 then return nil,DEADLINE_ERROR end
              return table.unpack(result,1,result.n)
            end
          end
          return proxy
        end,
      })
    end,remaining)
  end)
  -- LuaSocket normally closes on success/failure. On deadline or exception
  -- the nested coroutine may be suspended; close the owned socket ourselves.
  pcall(close_socket)
  if not ok then return nil,"HTTP transport exception: "..tostring(success) end
  if not success then return nil,"HTTP transport failed: "..tostring(code) end
  response_code=tonumber(code)
  if response_code~=200 and response_code~=202 then
    return nil,"HTTP status "..tostring(code).." ("..tostring(status)..")",response_code
  end
  local valid,data=pcall(json.decode,table.concat(chunks))
  if not valid or type(data)~="table" then return nil,"invalid JSON" end
  return data,nil,response_code
end
local function validate(data)
  if data.protocol~=C.PROTOCOL_NAME or tonumber(data.api_version)~=C.PROTOCOL_VERSION then
    return nil,"incompatible protocol/API version"
  end
  if not U.uuid_valid(data.id) then return nil,"invalid installation ID" end
  if data.platform~="linux" and data.platform~="windows" then
    return nil,"unknown operating system platform"
  end
  data.id=data.id:lower()
  return data
end
local function fetch(host,port,path)
  local data,err,status=request_json(host,port,path)
  if not data then return nil,err,status end
  return validate(data)
end
function M.fetch_info(host,port) return fetch(host,port,"/v2/info") end
function M.fetch_health(host,port)
  local data,err=fetch(host,port,"/v2/health")
  if not data then return nil,err end
  if data.status~="running" then return nil,"agent not reporting running" end
  return data
end
function M.fetch_metrics(host,port) return fetch(host,port,"/v2/metrics") end
function M.control(host,port,uuid,key,action)
  if action~="shutdown" and action~="suspend" and action~="reboot" then return nil,"invalid power action" end
  if not SHA.hmac_hex(key,"") then return nil,"missing/invalid 256-bit control key" end
  local challenge,err,challenge_status=fetch(host,port,"/v2/challenge")
  if not challenge then return nil,err,challenge_status end
  if challenge.id~=uuid then return nil,"ID mismatch at challenge endpoint" end
  local nonce=challenge.nonce
  if type(nonce)~="string" or #nonce~=48 or not nonce:match("^[0-9a-f]+$") then
    return nil,"invalid challenge nonce"
  end
  local path="/v2/power/"..action
  local proof=SHA.hmac_hex(key,"POST\n"..path.."\n"..nonce.."\n")
  local answer,post_err,status=request_json(host,port,path,"POST",{
    ["Content-Length"]="0",["X-ComputerHost-Nonce"]=nonce,["X-ComputerHost-Signature"]=proof,
  })
  if not answer then return nil,post_err,status end
  local ok,validation_err=validate(answer)
  if not ok then return nil,validation_err end
  if answer.id~=uuid or answer.accepted~=true or answer.action~=action or status~=202 then
    return nil,"power command not acknowledged"
  end
  return true,nil
end
return M
