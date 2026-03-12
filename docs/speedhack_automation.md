# Cheat Engine Speedhack Automation (Windows)

These scripts automate applying CE speedhack to multiple Isaac processes without selecting each process manually.

## Scripts

- `scripts/ce_speedhack_once.lua`
  - One-shot: applies speedhack to all currently running target processes.
- `scripts/ce_speedhack_watch.lua`
  - Watch mode: keeps scanning process list and auto-applies speedhack to newly launched target processes.
- `scripts/install_ce_speedhack_watch.ps1`
  - Installs/removes an autorun Lua file in Cheat Engine so watch mode starts automatically when CE launches.

## Option 1: One-Shot (manual run in CE)

1. Open Cheat Engine.
2. Open Lua Engine.
3. Run:

```lua
ISAAC_SPEEDHACK_SPEED = 10.0
dofile([[C:\Projects\binding-of-ai\scripts\ce_speedhack_once.lua]])
```

Use this when all Isaac instances are already running and you just want to apply speed once.

## Option 2: Watch Mode (manual run in CE)

1. Open Cheat Engine.
2. Open Lua Engine.
3. Run:

```lua
ISAAC_SPEEDHACK_SPEED = 10.0
ISAAC_SPEEDHACK_SCAN_MS = 1000
dofile([[C:\Projects\binding-of-ai\scripts\ce_speedhack_watch.lua]])
```

Stop watcher:

```lua
ISAAC_SPEEDHACK_WATCH.stop()
```

Use this when launcher starts workers in staggered order and you want CE to catch each one automatically.

## Option 3: CE Autorun (persistent)

Install watcher autorun:

```powershell
.\scripts\install_ce_speedhack_watch.ps1 -Action Install -Speed 10.0 -TargetProcess isaac-ng.exe -ScanIntervalMs 1000
```

Install and launch CE:

```powershell
.\scripts\install_ce_speedhack_watch.ps1 -Action Install -Speed 10.0 -LaunchCheatEngine
```

Remove autorun:

```powershell
.\scripts\install_ce_speedhack_watch.ps1 -Action Uninstall
```

Use this for the least manual overhead across sessions.
