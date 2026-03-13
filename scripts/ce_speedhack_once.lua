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
local ATTACH_SETTLE_MS = tonumber(
  _G.ISAAC_SPEEDHACK_ATTACH_SETTLE_MS or os.getenv("ISAAC_SPEEDHACK_ATTACH_SETTLE_MS") or ""
) or 100

local function log(msg)
  print(("[isaac-speedhack-once] %s"):format(msg))
end

local function install_ce_helper_workaround()
  if _G.ISAAC_SPEEDHACK_CELIB_WRAPPED then
    return
  end

  local original_inject = injectCEHelperLib
  if type(original_inject) ~= "function" then
    return
  end

  local function fixed_inject()
    if getAddressSafe("csenter") ~= nil then
      return true
    end

    local script
    if targetIsX86() then
      script = [[
alloc(cespinlock,32)
cespinlock:
]]

      if targetIs64Bit() then
        if getABI() == 0 then
          script = script .. [[
lock bts [rcx],0
]]
        else
          script = script .. [[
lock bts [rdi],0
]]
        end
      else
        script = script .. [[
mov eax,[esp+4]
lock bts [eax],0
]]
      end

      script = script .. [[
jc cespinlock_wait
ret

cespinlock_wait:
pause
jmp cespinlock
]]
    else
      error("todo: implement a spinlock for arm (could halfass it and just call an api)")
    end

    script = script .. [[
{$c}
#include <celib.h>
extern void cespinlock(int *lock);
#ifdef _WIN32
  static int getCurrentThreadID(void)
  {
    return 0;
  }
#else
  extern int gettid();
  int getCurrentThreadID()
  {
    return gettid();
  }
#endif

void csenter(cecs *cs)
{
  cespinlock(&cs->locked);
  cs->threadid=getCurrentThreadID();
  cs->lockcount=1;
}

void csleave(cecs *cs)
{
  cs->lockcount=0;
  cs->threadid=0;
  cs->locked=0;
}
{$asm}
]]

    local ok, err = autoAssemble(script)
    if ok then
      if err and err.ccodesymbols then
        err.ccodesymbols.name = "CELib"
      end
      return true
    end
    return false, err
  end

  injectCEHelperLib = function()
    local ok, result, err = pcall(original_inject)
    if ok and result then
      return result, err
    end

    local original_err = ok and err or result
    local err_text = tostring(original_err)
    if err_text:find("getCurrentThreadID", 1, true) then
      if not _G.ISAAC_SPEEDHACK_CELIB_WORKAROUND_LOGGED then
        _G.ISAAC_SPEEDHACK_CELIB_WORKAROUND_LOGGED = true
        log("Applying CE 7.6 celib workaround for getCurrentThreadID")
      end
      return fixed_inject()
    end

    if ok then
      return result, err
    end
    return false, tostring(result)
  end

  _G.ISAAC_SPEEDHACK_CELIB_WRAPPED = true
end

install_ce_helper_workaround()

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
  if ATTACH_SETTLE_MS > 0 then
    sleep(ATTACH_SETTLE_MS)
  end
  pcall(function()
    reinitializeSymbolhandler()
  end)

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
