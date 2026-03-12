-- Apply Cheat Engine speedhack to all currently running Isaac processes.
-- Run from CE Lua Engine:
--   dofile([[C:\Projects\binding-of-ai\scripts\ce_speedhack_once.lua]])
--
-- Optional overrides before dofile:
--   ISAAC_SPEEDHACK_TARGET = "isaac-ng.exe"
--   ISAAC_SPEEDHACK_SPEED = 10.0

local TARGET_PROCESS = string.lower(
  tostring(_G.ISAAC_SPEEDHACK_TARGET or os.getenv("ISAAC_SPEEDHACK_TARGET") or "isaac-ng.exe")
)
local TARGET_NO_EXE = TARGET_PROCESS:gsub("%.exe$", "")
local TARGET_SPEED = tonumber(
  _G.ISAAC_SPEEDHACK_SPEED or os.getenv("ISAAC_SPEEDHACK_SPEED") or ""
) or 10.0

local function log(msg)
  print(("[isaac-speedhack-once] %s"):format(msg))
end

local function matches_target(process_name)
  local name = string.lower(tostring(process_name or ""))
  if name == TARGET_PROCESS or name == TARGET_NO_EXE then
    return true
  end
  if name:find(TARGET_PROCESS, 1, true) then
    return true
  end
  if name:find(TARGET_NO_EXE, 1, true) then
    return true
  end
  return false
end

local function attach_and_speedhack(pid)
  local ok_open, open_err = pcall(function()
    openProcess(pid)
  end)
  if not ok_open then
    return false, ("openProcess failed: %s"):format(tostring(open_err))
  end
  if getOpenedProcessID() ~= pid then
    return false, "openProcess did not attach to requested pid"
  end

  local ok_speed, speed_err = pcall(function()
    speedhack_setSpeed(TARGET_SPEED)
  end)
  if not ok_speed then
    return false, ("speedhack_setSpeed failed: %s"):format(tostring(speed_err))
  end
  return true, nil
end

local process_list = getProcesslist() or {}
local matched = 0
local applied = 0
local failed = 0

for pid_key, process_name in pairs(process_list) do
  if matches_target(process_name) then
    matched = matched + 1
    local pid = tonumber(pid_key)
    if pid then
      local ok, err = attach_and_speedhack(pid)
      if ok then
        applied = applied + 1
        log(("Applied %.2fx to pid=%d (%s)"):format(TARGET_SPEED, pid, tostring(process_name)))
      else
        failed = failed + 1
        log(("Failed pid=%d (%s): %s"):format(pid, tostring(process_name), tostring(err)))
      end
    else
      failed = failed + 1
      log(("Skipping non-numeric pid key=%s (%s)"):format(tostring(pid_key), tostring(process_name)))
    end
  end
end

if matched == 0 then
  log(("No running processes matched '%s'"):format(TARGET_PROCESS))
else
  log(("Done. matched=%d applied=%d failed=%d"):format(matched, applied, failed))
end
