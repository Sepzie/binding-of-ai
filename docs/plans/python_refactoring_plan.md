# Python Codebase Refactoring Plan

**Date**: 2025-03-12
**Scope**: All Python code in `python/`, `scripts/`
**Goal**: Eliminate duplication, clarify module responsibilities, and make the architecture scalable as new training phases and evaluation modes are added.

---

## Current State Summary

The codebase has 12 Python files with generally good design (dataclass configs, SB3 callbacks, checkpoint metadata). However, growth has introduced duplication and blurred module boundaries. The biggest issues are:

- Game settings dict constructed identically in two places
- `IsaacEnv` is a god object (TCP, observations, diagnostics, game commands)
- Competing checkpoint path utilities across three modules
- No shared data contracts for game state or episode results

---

## Refactoring Items

### 1. Move game settings serialization into `Config`

**Problem**: `_build_game_settings()` in `train.py` and the identical inline dict in `evaluate.py` duplicate the same 20-field mapping. Adding a new phase field means updating both.

**Fix**: Add a `to_game_settings() -> dict` method on the `Config` dataclass in `config.py`. It knows its own fields — it should own serialization to the Lua wire format.

```python
# config.py
class Config:
    ...
    def to_game_settings(self) -> dict:
        return {
            "enemy_type": self.phase.enemy_type,
            ...
            "frame_skip": self.env.frame_skip,
            "max_episode_ticks": self.env.max_episode_steps,
        }
```

Remove `_build_game_settings()` from `train.py` and the inline dict from `evaluate.py`. Both call `config.to_game_settings()`.

**Files changed**: `config.py`, `train.py`, `evaluate.py`

---

### 2. Auto-configure game on first `reset()`

**Problem**: Callers must remember to call `env.configure_game(settings)` after constructing `IsaacEnv`. Forgetting this (as evaluate.py did) causes silent wrong behavior — the Lua mod runs with stale defaults.

**Fix**: `IsaacEnv` already receives the full `Config` in `__init__`. Store the game settings and send them automatically on the first `reset()` call (or reconnect). Add a `_configured` flag to avoid re-sending on every reset unless settings change.

```python
# isaac_env.py
def __init__(self, config):
    ...
    self._game_settings = config.to_game_settings()
    self._configured = False

def reset(self, **kwargs):
    ...
    if not self._configured:
        self.configure_game(self._game_settings)
        self._configured = True
    ...
```

Keep `configure_game()` public for cases where settings need to change mid-session (e.g., curriculum learning), but make it no longer required for basic usage.

**Files changed**: `isaac_env.py`, `train.py` (remove manual calls), `evaluate.py` (remove manual calls)

---

### 3. Extract `NetworkClient` from `IsaacEnv`

**Problem**: `IsaacEnv` (397 lines) handles TCP socket management (connect, disconnect, reconnect, send, receive, timeout, buffering) alongside gymnasium env logic. These are independent concerns.

**Fix**: Extract a `NetworkClient` class that owns the socket lifecycle:

```python
# network_client.py
class NetworkClient:
    def __init__(self, host: str, port: int, timeout: float):
        ...
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def send(self, message: dict) -> None: ...
    def receive(self) -> dict: ...
    def flush(self) -> None: ...
```

`IsaacEnv` holds a `NetworkClient` and delegates all socket operations to it. This also makes the protocol testable in isolation.

**Files changed**: New `network_client.py`, `isaac_env.py` (refactor to use client)

---

### 4. Consolidate checkpoint path utilities

**Problem**: Three modules have overlapping checkpoint logic:
- `utils.py`: `find_latest_checkpoint()`, `find_latest_compatible_checkpoint()`, legacy regex patterns
- `checkpoint_manager.py`: `find_latest()`, `find_latest_for_config()`, `find_latest_compatible()` (static methods)
- `evaluate.py`: Its own `CHECKPOINT_ROOT`, `_find_run_dir()`, `resolve_model_path()`

**Fix**: Make `CheckpointManager` the single authority for checkpoint discovery. Move `resolve_model_path` and `_find_run_dir` into it as static methods. Remove the legacy helpers from `utils.py` (they duplicate `CheckpointManager` functionality and use the old flat folder structure that was already migrated away).

Keep `utils.py` for generic path helpers only (`get_repo_root`, `get_checkpoint_dir`, `get_log_dir`, `checkpoint_timestamp`).

**Files changed**: `checkpoint_manager.py`, `evaluate.py`, `utils.py`, `train.py` (update imports)

---

### 5. Define `GameState` dataclass

**Problem**: Game state arrives as a raw dict from the Lua mod. Every consumer (`IsaacEnv`, `RewardShaper`, callbacks) accesses it with string keys like `state["player_x"]`, `state.get("room_cleared", False)`. A typo or schema change silently breaks things.

**Fix**: Define a `GameState` dataclass in a new `game_state.py` (or in `config.py`). Parse the raw dict into it once in `IsaacEnv._receive()` or at the boundary.

```python
@dataclass
class GameState:
    player_x: float
    player_y: float
    player_hp: int
    enemies: list[dict]
    room_cleared: bool
    ...
```

`RewardShaper.compute()` and observation building in `IsaacEnv` would operate on typed fields instead of dict lookups.

**Files changed**: New `game_state.py`, `isaac_env.py`, `reward.py`

---

### 6. Clean up launcher hardcoded paths

**Problem**: `launcher.py` has hardcoded Windows paths for Sandboxie and Steam, plus the Isaac app ID. These break on non-standard installs.

**Fix**: Read from environment variables with current values as defaults:

```python
SANDBOXIE_START = os.getenv("SANDBOXIE_PATH", r"C:\Program Files\Sandboxie-Plus\Start.exe")
STEAM_EXE = os.getenv("STEAM_PATH", r"C:\Program Files (x86)\Steam\steam.exe")
```

**Files changed**: `launcher.py`

---

### 7. Extract shared key-sending utility

**Problem**: `launcher.py` and `test_keys.py` both implement `_send_key()` with identical Win32 API calls.

**Fix**: Move `_send_key()` (and related Win32 helpers like `get_pid_from_hwnd`, `get_window_rect`) into a `win32_utils.py` module. Both files import from there.

**Files changed**: New `win32_utils.py`, `launcher.py`, `test_keys.py`

---

## Execution Order

The items above are ordered by dependency — each builds on the previous:

| Step | Item | Depends On | Risk |
|------|------|------------|------|
| 1 | `Config.to_game_settings()` | — | Low (pure refactor) |
| 2 | Auto-configure on first `reset()` | Step 1 | Low (additive) |
| 3 | Extract `NetworkClient` | — | Medium (touches hot path) |
| 4 | Consolidate checkpoint utils | — | Low (move + delete) |
| 5 | `GameState` dataclass | — | Medium (wide surface area) |
| 6 | Launcher env vars | — | Low (trivial) |
| 7 | Shared key-sending util | — | Low (trivial) |

Steps 1-2 should be done together as they directly address the bug that prompted this plan. Steps 3-7 are independent of each other and can be done in any order.

---

## Out of Scope

These are things that would be nice but aren't worth doing now:

- **Unifying W&B integration into a manager class** — current scattered usage works fine and isn't causing bugs.
- **Abstract environment interface for callbacks** — over-engineering for one env implementation.
- **Parameterizing network architecture** — CNN dims are stable and not being experimented with.
- **Curriculum learning framework** — no concrete need yet; can be added when phases become dynamic.
- **Distributed training** — single-machine multi-worker is sufficient for current scale.
