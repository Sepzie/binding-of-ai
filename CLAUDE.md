# Project: Binding of Isaac RL Agent

## Workflow
- Agents working on this codebase MUST commit their work in logical chunks with informative commit descriptions as they work. Don't batch everything into one giant commit at the end.
- Use `.venv/bin/python` for all Python commands (no system `python`).
- options.ini can ONLY be edited while the game is closed.

## Architecture
- Lua mod (`mod/`) communicates with Python (`python/`) over TCP port 9999
- Game: Isaac Repentance v1.7.9b via Proton on Linux
- Track progress via CHECKLIST.md

## Documentary Stories
This project doubles as a case study for a YouTube documentary series. Development stories live in `docs/story/` as numbered entries (e.g. `001_the_protocol_wall.md`). These are narrative, diary-style write-ups capturing key moments, debugging sagas, and design insights. The user may ask for a new story entry at the end of a session — only write one when asked.
