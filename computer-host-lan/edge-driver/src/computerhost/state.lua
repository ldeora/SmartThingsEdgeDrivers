-- Pure logical state transitions for the SmartThings Computer Host controller.
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

-- Reboot completion requires a different kernel boot_id. For suspend, a
-- recoverable connectivity gap is enough to recognize a quick resume, while
-- a continuously responding agent is no longer 'suspending' after 30s.
-- The same conservative timeout clears a cancelled Windows shutdown after
-- 60s if its agent never went away (202 only means accepted).
function M.success(action,boot_changed,failed_polls,elapsed_seconds)
  if action=="wake" then return "running",true end
  if action=="reboot" then
    return boot_changed and "running" or "rebooting",boot_changed==true
  end
  if action=="shutdown" then
    if (elapsed_seconds or 0)>=60 then return "running",true end
    return "stopping",false
  end
  if action=="suspend" then
    if (failed_polls or 0)>0 or (elapsed_seconds or 0)>=30 then return "running",true end
    return "suspending",false
  end
  return "running",false
end

return M
