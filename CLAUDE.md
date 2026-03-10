# Project: Binding of Isaac RL Agent

## Workflow
- Agents working on this codebase MUST commit their work in logical chunks with informative commit descriptions as they work. Don't batch everything into one giant commit at the end.
- Use `.venv/bin/python` for all Python commands (no system `python`).
- options.ini can ONLY be edited while the game is closed.

## Architecture
- Lua mod (`mod/`) communicates with Python (`python/`) over TCP port 9999
- Game: Isaac Repentance v1.7.9b via Proton on Linux
- Track progress via CHECKLIST.md

## Wandb Run Management
- Always set `run_name` and `tags` in the wandb config section before launching a run.
- Name runs descriptively: include the phase and what changed, e.g. `"phase1a-high-entropy"`, `"phase1a-6enemies-lr1e4"`.
- Always tag the phase (e.g. `["phase1a"]`). Add tags for what's being tested (e.g. `["phase1a", "entropy-sweep"]`).
- When making a config change for a new experiment, update `run_name` and `tags` to match.
- Dashboard: https://wandb.ai/sepzie1/binding-of-ai

## Documentary Stories
This project doubles as a case study for a YouTube documentary series. Development stories live in `docs/story/` as numbered entries (e.g. `001_the_protocol_wall.md`). These are narrative, diary-style write-ups capturing key moments, debugging sagas, and design insights. The user may ask for a new story entry at the end of a session — only write one when asked.
