# Project: Binding of Isaac RL Agent

## Workflow
- Agents working on this codebase MUST commit their work in logical chunks with informative commit descriptions as they work. Don't batch everything into one giant commit at the end.
- Use `.venv/bin/python` for all Python commands (no system `python`).
- options.ini can ONLY be edited while the game is closed.

## Architecture
- Lua mod (`mod/`) communicates with Python (`python/`) over TCP port 9999
- Game: Isaac Repentance v1.7.9b via Proton on Linux
- Mod directory: `~/.local/share/Steam/steamapps/common/The Binding of Isaac Rebirth/mods/`
- Track progress via CHECKLIST.md
