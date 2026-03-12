-- Watch running processes and apply Cheat Engine speedhack to Isaac automatically.
-- Run from CE Lua Engine:
--   dofile([[C:\Projects\binding-of-ai\scripts\ce_speedhack_watch.lua]])
--
-- Optional overrides before dofile:
--   ISAAC_SPEEDHACK_TARGET = "isaac-ng.exe"
--   ISAAC_SPEEDHACK_SPEED = 10.0
--   ISAAC_SPEEDHACK_SCAN_MS = 1000
--
-- After loading:
--   ISAAC_SPEEDHACK_WATCH.stop()
--   ISAAC_SPEEDHACK_WATCH.scan_once()

local TARGET_PROCESS = string.lower(
  tostring(_G.ISAAC_SPEEDHACK_TARGET or os.getenv("ISAAC_SPEEDHACK_TARGET") or "isaac-ng.exe")
)
local TARGET_NO_EXE = TARGET_PROCESS:gsub("%.exe$", "")
local TARGET_SPEED = tonumber(
  _G.ISAAC_SPEEDHACK_SPEED or os.getenv("ISAAC_SPEEDHACK_SPEED") or ""
) or 10.0
local SCAN_INTERVAL_MS = tonumber(
  _G.ISAAC_SPEEDHACK_SCAN_MS or os.getenv("ISAAC_SPEEDHACK_SCAN_MS") or ""
) or 1000
local RETRY_COUNT = tonumber(
  _G.ISAAC_SPEEDHACK_RETRY_COUNT or os.getenv("ISAAC_SPEEDHACK_RETRY_COUNT") or ""
) or 3
local RETRY_SLEEP_MS = tonumber(
  _G.ISAAC_SPEEDHACK_RETRY_SLEEP_MS or os.getenv("ISAAC_SPEEDHACK_RETRY_SLEEP_MS") or ""
) or 250

local function log(msg)
  print(("[isaac-speedhack-watch] %s"):format(msg))
end

local function destroy_timer(timer)
  if not timer then
    return
  end
  pcall(function()
    timer.Enabled = false
  end)
  pcall(function()
    timer.destroy()
  end)
  pcall(function()
    timer:destroy()
  end)
end

if _G.ISAAC_SPEEDHACK_WATCH and _G.ISAAC_SPEEDHACK_WATCH.timer then
  destroy_timer(_G.ISAAC_SPEEDHACK_WATCH.timer)
end

local applied_pids = {}

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

  for _, module in ipairs(modules) do
    local module_name = string.lower(tostring(module.Name or ""))
    if module_name:find("speedhack-", 1, true) then
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
      sleep(RETRY_SLEEP_MS)
      if has_speedhack_module(pid) then
        return true, nil
      end
      last_err = "speedhack module not present after setSpeed"
    end
  end
  return false, last_err
end

local function scan_once()
  local process_list = getProcesslist() or {}
  local live_targets = {}

  for pid_key, process_name in pairs(process_list) do
    if matches_target(process_name) then
      local pid = tonumber(pid_key)
      if pid then
        live_targets[pid] = true
        if applied_pids[pid] and not has_speedhack_module(pid) then
          applied_pids[pid] = nil
          log(("Speedhack module missing for pid=%d; retrying"):format(pid))
        end

        if not applied_pids[pid] then
          local ok, err = apply_with_verification(pid)
          if ok then
            applied_pids[pid] = true
            log(("Applied %.2fx to pid=%d (%s)"):format(TARGET_SPEED, pid, tostring(process_name)))
          else
            log(("Failed pid=%d (%s): %s"):format(pid, tostring(process_name), tostring(err)))
          end
        end
      end
    end
  end

  for pid, _ in pairs(applied_pids) do
    if not live_targets[pid] then
      applied_pids[pid] = nil
    end
  end
end

local timer = createTimer(nil, false)
timer.Interval = SCAN_INTERVAL_MS
timer.OnTimer = function()
  scan_once()
end
timer.Enabled = true

local function stop_watch()
  destroy_timer(timer)
  _G.ISAAC_SPEEDHACK_WATCH = nil
  log("Stopped watcher")
end

_G.ISAAC_SPEEDHACK_WATCH = {
  timer = timer,
  stop = stop_watch,
  scan_once = scan_once,
  speed = TARGET_SPEED,
  target = TARGET_PROCESS,
  interval_ms = SCAN_INTERVAL_MS,
}

log(
  ("Started: target='%s' speed=%.2fx interval=%dms retries=%d"):format(
    TARGET_PROCESS,
    TARGET_SPEED,
    SCAN_INTERVAL_MS,
    RETRY_COUNT
  )
)
scan_once()
