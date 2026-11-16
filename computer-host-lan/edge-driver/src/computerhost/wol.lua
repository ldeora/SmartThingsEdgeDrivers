local cosock=require "cosock"
local U=require "computerhost.util"
local M={}
function M.parse_mac(address)
  if not U.valid_wol_mac(address) then return nil end
  local compact=address:gsub("[-:]",""):lower()
  return compact:gsub("..",function(pair) return string.char(tonumber(pair,16)) end)
end
function M.packet(mac)
  local six=M.parse_mac(mac)
  if not six then return nil end
  return string.rep(string.char(255),6)..string.rep(six,16)
end
function M.send(mac,broadcast,port)
  local payload=M.packet(mac)
  if not payload then return false,"missing or invalid unicast Ethernet MAC" end
  if not U.is_ipv4(broadcast) then return false,"invalid IPv4 broadcast address" end
  port=tonumber(port)
  if not port or port<1 or port>65535 then return false,"invalid UDP port" end
  local udp,err=cosock.socket.udp()
  if not udp then return false,tostring(err) end
  local ok,result,reason=pcall(function()
    udp:settimeout(2)
    local enabled,enable_err=udp:setoption("broadcast",true)
    if not enabled then return false,"cannot enable broadcast: "..tostring(enable_err) end
    -- Three immediate packets help with occasional packet loss. Verification
    -- happens in the regular health poll loop, never by optimistic switch ON.
    for _=1,3 do
      local sent,send_err=udp:sendto(payload,broadcast,port)
      if not sent then return false,"UDP send error: "..tostring(send_err) end
    end
    return true
  end)
  pcall(function() udp:close() end)
  if not ok then return false,tostring(result) end
  return result,reason
end
return M
