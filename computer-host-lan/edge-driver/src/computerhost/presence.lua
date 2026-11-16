-- Pure classification of connectivity failures. These are heuristics, not
-- electrical power-state measurements. Never classify a protocol rejection,
-- unexpected installation UUID, or Lua runtime error as "powered off".
local M={}
function M.classify_failure(reason)
  if type(reason)~="string" then return "unknown" end
  local e=reason:lower()
  -- If the target's TCP stack rejects a connection, the machine is typically
  -- running even if its HTTP agent/service is not. A firewall or router may
  -- also generate a reject, so this is only evidence, not certainty.
  if e:find("connection refused",1,true) or e:find("os error 111",1,true) then
    return "agent_unavailable"
  end
  if e:find("timeout",1,true) or e:find("timed out",1,true)
      or e:find("host is down",1,true)
      or e:find("host unreachable",1,true)
      or e:find("network unreachable",1,true)
      or e:find("network is unreachable",1,true)
      or e:find("no route to host",1,true)
      or e:find("network is down",1,true)
      or e:find("os error 113",1,true)
      or e:find("os error 110",1,true) then
    return "host_unreachable"
  end
  return "unknown"
end
return M
