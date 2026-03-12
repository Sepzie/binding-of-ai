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
local VERIFY_MODULE = tostring(
  _G.ISAAC_SPEEDHACK_VERIFY_MODULE or os.getenv("ISAAC_SPEEDHACK_VERIFY_MODULE") or "0"
):lower() == "1"
local RETRY_COUNT = tonumber(
  _G.ISAAC_SPEEDHACK_RETRY_COUNT or os.getenv("ISAAC_SPEEDHACK_RETRY_COUNT") or ""
) or 3
local RETRY_SLEEP_MS = tonumber(
  _G.ISAAC_SPEEDHACK_RETRY_SLEEP_MS or os.getenv("ISAAC_SPEEDHACK_RETRY_SLEEP_MS") or ""
) or 250

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

local function has_speedhack_module(pid)
  local ok_enum, modules = pcall(function()
    return enumModules(pid)
  end)
  if not ok_enum or type(modules) ~= "table" then
    return false
  end

  for _, module in pairs(modules) do
    local module_name = string.lower(tostring((type(module) == "table" and module.Name) or ""))
    if module_name:find("speedhack", 1, true) then
      return true
    end
  end
  return false
end

local function apply_with_verification(pid)
  local last_err = "unknown error"
  for _ = 1, RETRY_COUNT do
    local ok, err = attach_and_speedhack(pid)
    if not ok then
      last_err = err
    else
      if not VERIFY_MODULE then
        return true, nil
      end
      sleep(RETRY_SLEEP_MS)
      if has_speedhack_module(pid) then
        return true, nil
      end
      last_err = "speedhack module not present after setSpeed"
    end
  end
  return false, last_err
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
      local ok, err = apply_with_verification(pid)
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
