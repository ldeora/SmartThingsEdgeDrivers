-- Pure logical state transitions for the SmartThings Computer Host controller.
-- No network transport can prove S3/S5 remotely. Document state inference.
local M={}

-- How long an acknowledged shutdown counts as in progress while the agent
-- still answers. Windows shuts down after a 15-second countdown without
-- forcing applications closed; an agent that still answers after this period
-- means the shutdown was cancelled or is blocked, so the host is 'running'.
M.SHUTDOWN_GRACE_SECONDS=60

-- True while an acknowledged shutdown is within its grace period. During this
-- time the switch stays at the commanded OFF and duplicate shutdown requests
-- are not sent again.
function M.shutdown_in_progress(action,elapsed_seconds)
  return action=="shutdown" and (elapsed_seconds or 0)<M.SHUTDOWN_GRACE_SECONDS
end

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
    -- A new boot ID is positive evidence that the host is running again.
    -- It supersedes shutdown grace and clears the obsolete pending action.
    if boot_changed then return "running",true end
    -- A slow Windows shutdown may still complete later; show Running after
    -- the grace period without discarding its action context. The outer
    -- 180-second bound eventually expires a truly cancelled shutdown.
    if not M.shutdown_in_progress(action,elapsed_seconds) then return "running",false end
    return "stopping",false
  end
  if action=="suspend" then
    -- Do not interpret one unrelated transient network error as a resume.
    if (failed_polls or 0)>=2 then return "running",true end
    if (elapsed_seconds or 0)>=30 then return "running",false end
    return "suspending",false
  end
  return "running",false
end

return M
