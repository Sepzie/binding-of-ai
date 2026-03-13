# Plan: Phase 0d — Wall Penalty + Obstacle Navigation

**Date**: 2026-03-13
**Goal**: Teach Isaac to navigate around obstacles while collecting coins, and penalize wall/obstacle collisions to fix the wall-walking behavior.

---

## Problem Statement

The current model (phase0c-multicoin-contpos) has learned efficient coin collection in empty rooms but exhibits three navigation flaws:

1. **Wall walking**: Isaac sometimes walks directly into walls for several seconds
2. **Coin orbiting/pacing**: Near pickups, Isaac overshoots or oscillates (likely frameskip-related, separate fix)
3. **Empty room only**: The model has never seen interior obstacles — the moment a rock appears, it will fail

All three worsen in real gameplay where rooms have complex layouts with rocks, pits, and obstacles.

---

## Implementation Items

### 1. Wall/Obstacle Collision Penalty (Reward)

**Problem**: Isaac has no disincentive for walking into walls. The only cost is wasted time (time_penalty = -0.05/step), which is too small to learn "don't walk into walls."

**Approach**: Detect when Isaac's position hasn't changed between steps despite issuing a movement action. This indicates collision with a wall or obstacle. Apply a per-step penalty.

#### Lua side (`state_serializer.lua`)
- No changes needed. The player's continuous position (`pos_x`, `pos_y`) is already sent every step.

#### Python side (`reward.py`)
- Add `wall_collision: float = -0.5` to `RewardConfig`
- In `RewardShaper.compute()`, detect "stuck" condition:
  - Compare `state.player.position` to `self.prev_state.player.position`
  - If Euclidean distance < threshold (e.g., 1.0 world units) AND the agent issued a movement action (not no-op), apply penalty
  - The action check is important: standing still deliberately (shoot-only) should NOT be penalized
- Log as `reward_components["wall_collision"]`

#### Challenge: Action context
- `RewardShaper.compute()` currently only receives the game state, not the action taken. We need to pass the action to `compute()` or store it.
- **Simplest approach**: Add an optional `action` parameter to `compute()`. `IsaacEnv.step()` already has the action — pass it through.
- Alternative: just check position delta without action context. Penalize any step where Isaac barely moves. The downside is that this penalizes situations where Isaac is correctly standing still to shoot (future phases). For the current coin-only phase, Isaac should always be moving, so this is fine for now. **Use the simpler approach for now, add action context later when shooting phases need it.**

#### Config
- Add `wall_collision_penalty: float` to `RewardConfig` (default 0.0 to not break existing configs)
- Set to `-0.5` in the phase0d config

---

### 2. Obstacle Spawning (Lua)

**Problem**: The mod has no infrastructure for spawning grid entities (rocks, pits, etc). It only spawns regular entities (enemies, pickups) via `Isaac.Spawn()`. Rocks are **grid entities** and require `Isaac.GridEntitySpawn()` or similar.

**Approach**: Add a configurable obstacle spawning system to `game_control.lua` that places random rocks at episode reset.

#### Isaac API for grid entities

Grid entity spawning in Isaac uses:
```lua
-- Spawn a grid entity at a specific grid index
Isaac.GridEntitySpawn(gridEntityType, variant, gridIndex, forced)
-- Or via room object:
room:SpawnGridEntity(gridIndex, gridEntityType, variant, seed, varData)
```

Where `gridIndex` is a linear index into the room grid: `gridIndex = y * gridWidth + x` (0-indexed).

Grid entity types we care about:
- `GridEntityType.GRID_ROCK` (2) — standard destructible rock
- `GridEntityType.GRID_ROCKB` (3) — harder rock
- `GridEntityType.GRID_ROCKT` (4) — stone block (indestructible)
- `GridEntityType.GRID_PIT` (8) — pit (walkable with flight)

Start with `GRID_ROCKT` (4, indestructible stone) to keep it simple — destructible rocks add complexity since the model could accidentally destroy them.

#### Reachability: preventing coin islands

Random rock placement can create enclosed areas where coins spawn but Isaac can't reach them. This is the hardest part of the implementation.

**Option A: Flood fill validation**
After placing rocks, run a flood fill from Isaac's spawn position. If any walkable tile is unreachable, remove the last-placed rock and retry. This guarantees reachability but is more complex to implement in Lua.

**Option B: Conservative placement rules**
Only place rocks in positions that can't create enclosures:
- Never place rocks adjacent to walls (leaves gaps)
- Never place rocks adjacent to each other (prevents walls forming)
- Limit to N rocks (e.g., 3-5) in a 13x7 room

**Option C: Spawn coins only in reachable positions**
Use Isaac's `room:FindFreePickupSpawnPosition()` which avoids grid obstacles. Combined with the existing random spawn logic, coins should always land in walkable areas. The risk is that rocks could still create isolated regions.

**Recommendation: Option B for now, Option A later.** Conservative placement with a minimum spacing constraint is simple, fast, and sufficient for early obstacle training. When we move to hand-crafted mazes or complex layouts, we'll need flood fill anyway, so that can be built then.

#### Lua architecture considerations

The current spawning code in `game_control.lua` has a flat structure — `spawnEnemies()` and `spawnPenny()` are top-level functions. Before adding `spawnObstacles()`, consider:

1. **Spawning order matters**: Obstacles must be spawned BEFORE pickups and enemies, so their spawn positions avoid obstacles.

2. **Obstacle clearing on reset**: Grid entities persist between episodes unless explicitly removed. `GameControl.resetEpisode()` must clear spawned obstacles. Isaac's `room:RemoveGridEntity(gridIndex, pathTrail, force)` handles this.

3. **Configuration pattern**: Follow the existing pattern — add config fields to `config.lua`, wire through `GameControl.configure()`, add to Python's `PhaseConfig` and `Config.to_game_settings()`.

#### New config fields

```lua
-- config.lua
Config.SPAWN_OBSTACLES = false
Config.OBSTACLE_COUNT = 0         -- number of rocks to spawn
Config.OBSTACLE_TYPE = 4          -- GridEntityType (4 = GRID_ROCKT, indestructible)
Config.OBSTACLE_MIN_SPACING = 2   -- minimum grid cells between rocks (prevents wall formation)
```

#### Implementation in `game_control.lua`

```lua
function GameControl.spawnObstacles(game)
    if not Config.SPAWN_OBSTACLES or Config.OBSTACLE_COUNT <= 0 then
        return
    end
    local room = game:GetRoom()
    local gridWidth = room:GetGridWidth()

    -- Build list of valid grid positions (not walls, not near player spawn, not near edges)
    local candidates = {}
    for gy = 2, Config.GRID_HEIGHT - 1 do  -- skip top/bottom row (wall-adjacent)
        for gx = 2, Config.GRID_WIDTH - 1 do  -- skip left/right column
            local idx = gy * gridWidth + gx
            local existing = room:GetGridEntity(idx)
            if not existing then
                table.insert(candidates, {gx = gx, gy = gy, idx = idx})
            end
        end
    end

    -- Place rocks with minimum spacing constraint
    local placed = {}
    local attempts = 0
    while #placed < Config.OBSTACLE_COUNT and attempts < 100 do
        attempts = attempts + 1
        local pick = candidates[math.random(#candidates)]
        -- Check spacing against already-placed rocks
        local tooClose = false
        for _, p in ipairs(placed) do
            if math.abs(pick.gx - p.gx) < Config.OBSTACLE_MIN_SPACING
               and math.abs(pick.gy - p.gy) < Config.OBSTACLE_MIN_SPACING then
                tooClose = true
                break
            end
        end
        if not tooClose then
            room:SpawnGridEntity(pick.idx, Config.OBSTACLE_TYPE, 0, 0, 0)
            table.insert(placed, pick)
        end
    end
end
```

#### Obstacle clearing on reset

In `GameControl.resetEpisode()`, before spawning new obstacles:
```lua
function GameControl.clearObstacles(game)
    local room = game:GetRoom()
    local gridSize = room:GetGridSize()
    for idx = 0, gridSize - 1 do
        local entity = room:GetGridEntity(idx)
        if entity then
            local gType = entity:GetType()
            -- Only remove rocks we spawned (not natural walls)
            if gType == GridEntityType.GRID_ROCK
               or gType == GridEntityType.GRID_ROCKB
               or gType == GridEntityType.GRID_ROCKT
               or gType == GridEntityType.GRID_ROCK_ALT then
                room:RemoveGridEntity(idx, 0, false)
            end
        end
    end
end
```

**Important**: Call `clearObstacles()` → `spawnObstacles()` → `spawnPenny()` in that order during reset.

---

### 3. Episode steps increase

**Change**: Bump `max_episode_steps` from 800 to 1000 in the new config. This gives the agent more time per episode to practice navigating around obstacles (which take longer than straight-line paths).

---

### 4. Config and Python wiring

#### Python `PhaseConfig` additions:
```python
spawn_obstacles: bool = False
obstacle_count: int = 0
obstacle_type: int = 4        # GRID_ROCKT
obstacle_min_spacing: int = 2
```

#### `Config.to_game_settings()` additions:
```python
"spawn_obstacles": self.phase.spawn_obstacles,
"obstacle_count": self.phase.obstacle_count,
"obstacle_type": self.phase.obstacle_type,
"obstacle_min_spacing": self.phase.obstacle_min_spacing,
```

#### Lua `GameControl.configure()` additions:
```lua
if settings.spawn_obstacles ~= nil then
    Config.SPAWN_OBSTACLES = settings.spawn_obstacles
end
if settings.obstacle_count then
    Config.OBSTACLE_COUNT = settings.obstacle_count
end
if settings.obstacle_type then
    Config.OBSTACLE_TYPE = settings.obstacle_type
end
if settings.obstacle_min_spacing then
    Config.OBSTACLE_MIN_SPACING = settings.obstacle_min_spacing
end
```

---

### 5. Phase 0d config file

See `configs/phase0d-obstacles.yaml` (already created).

Key differences from phase0c:
- `wall_collision_penalty: -0.5` (new)
- `spawn_obstacles: true`, `obstacle_count: 3`, `obstacle_type: 4` (new)
- `max_episode_steps: 1000` (up from 800, more time to navigate around obstacles)
- No enemies, shooting disabled/masked (same as phase0c)

---

## Execution Order

| Step | What | Files Changed |
|------|------|---------------|
| 1 | Add `wall_collision_penalty` to RewardConfig + RewardShaper | `config.py`, `reward.py` |
| 2 | Add obstacle config fields to Python + Lua | `config.py`, `config.lua`, `game_control.lua` |
| 3 | Implement `spawnObstacles()` + `clearObstacles()` in Lua | `game_control.lua` |
| 4 | Wire obstacle config through `configure()` and `to_game_settings()` | `game_control.lua`, `config.py` |
| 5 | Update `resetEpisode()` to clear and respawn obstacles | `game_control.lua` |
| 6 | Create phase0d config | `configs/phase0d-obstacles.yaml` |
| 7 | Test with 1 worker, verify obstacles appear and get detected in grid | Manual |
| 8 | Run training, monitor wall_collision reward component | W&B |

---

## Future Extensions (not in scope)

- **Hand-crafted room layouts**: Load predefined obstacle patterns from a table/file for maze-like rooms
- **Flood fill reachability**: Required for complex layouts where conservative spacing isn't sufficient
- **Destructible obstacles**: Rocks that Isaac can bomb — adds strategic element
- **Pit spawning**: Pits require flight or bridging, more complex than rocks
- **Dynamic obstacle count curriculum**: Start with 0 rocks, increase as the model improves
