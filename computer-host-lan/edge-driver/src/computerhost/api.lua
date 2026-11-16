local cosock = require "cosock"
local http = cosock.asyncify "socket.http"
local json = require "st.json"
local C = require "computerhost.constants"
local U = require "computerhost.util"
local SHA = require "computerhost.sha256"
local M = {}
local MAX_RESPONSE = 32768

local function request_json(host,port,path,method,headers)
  local clean_host,clean_port=U.parse_host_port(host,port)
  if not clean_host then return nil,"invalid address" end
  local chunks,size={},0
  local response_code
  local url=string.format("http://%s:%d%s",U.host_for_url(clean_host),clean_port,path)
  local request_headers={
    ["Accept"]="application/json", ["User-Agent"]="SmartThings-ComputerHost/0.4.0-dev.1",
    ["Connection"]="close"
  }
  for k,v in pairs(headers or {}) do request_headers[k]=v end
  local ok,success,code,_,status=pcall(function()
    return http.request({url=url,method=method or "GET",headers=request_headers,
      sink=function(chunk)
        if chunk then
          size=size+#chunk
          if size>MAX_RESPONSE then return nil,"response too large" end
          chunks[#chunks+1]=chunk
        end
        return 1
      end,
      create=function()
        local sock=cosock.socket.tcp()
        sock:settimeout(C.HTTP_TIMEOUT)
        return sock
      end,
    })
  end)
  if not ok then return nil,"HTTP transport exception: "..tostring(success) end
  if not success then return nil,"HTTP transport failed: "..tostring(code) end
  response_code=tonumber(code)
  if response_code~=200 and response_code~=202 then
    return nil,"HTTP status "..tostring(code).." ("..tostring(status)..")"
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
  local data,err=request_json(host,port,path)
  if not data then return nil,err end
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
  local challenge,err=fetch(host,port,"/v2/challenge")
  if not challenge then return nil,err end
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
  if not answer then return nil,post_err end
  local ok,validation_err=validate(answer)
  if not ok then return nil,validation_err end
  if answer.id~=uuid or answer.accepted~=true or answer.action~=action or status~=202 then
    return nil,"power command not acknowledged"
  end
  return true,nil
end
return M
