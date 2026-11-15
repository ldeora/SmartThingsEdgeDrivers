-- Pure logical state transitions for the SmartThings Linux Host controller.
-- No network transport can prove S3/S5 remotely. Document state inference.
local M={}

-- Returns status, optional switch state and whether the pending action was
-- completed by sufficiently strong evidence. Called only after the configured
-- failure threshold; connection refusal alone must NOT confirm power-off.
function M.failure(action,kind,failed_polls,host_failures,threshold,assume_off)
  if failed_polls<threshold then return nil,nil,false end
  if action=="shutdown" or action=="suspend" then
    if kind=="host_unreachable" and host_failures>=threshold then
      return action=="shutdown" and "stopped" or "suspended","off",true
    end
    return action=="shutdown" and "stopping" or "suspending",nil,false
  end
  if action=="reboot" then return "rebooting",nil,false end
  if action=="wake" then
    -- Timeout after a magic packet indicates we have not confirmed a boot.
    return kind=="unknown" and "unknown" or "starting",nil,false
  end
  if kind=="agent_unavailable" then
    return "unreachable","on",false
  elseif kind=="host_unreachable" then
    return "unreachable",(assume_off and host_failures>=threshold) and "off" or nil,false
  end
  -- Wrong agent identity, protocol mismatch or unknown Lua/HTTP error:
  -- never infer a power state from these conditions.
  return "unknown",nil,false
end

-- A reboot is confirmed only by a different Linux kernel boot_id.
function M.success(action,boot_changed)
  if action=="wake" then return "running",true end
  if action=="reboot" then
    return boot_changed and "running" or "rebooting",boot_changed==true
  end
  if action=="shutdown" then return "stopping",false end
  if action=="suspend" then return "suspending",false end
  return "running",false
end

return M
