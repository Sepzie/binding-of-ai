# Runtime Architecture Plan

## Goal

Build a training runtime for Isaac that:

- never blocks the game thread on Python
- restarts episodes immediately after terminal states
- preserves clean episode boundaries for Gym/SB3
- tolerates death screens, menus, and short Python stalls
- maximizes rollout throughput

## Current Problem

The current design is a lockstep protocol:

- Lua `MC_POST_UPDATE` sends one state
- Lua blocks waiting for one Python action
- Python `step()` sends one action
- Python blocks waiting for one Lua state

This works only while both sides stay perfectly synchronized and Python responds fast enough. It breaks down around death screens because `MC_POST_UPDATE` may stop firing exactly when Python wants to reset the run.

## Recommended Design

### 1. Lua owns real-time control

Lua should own:

- action polling
- terminal detection
- immediate restart timing
- episode transitions

Python should not control the exact instant of reset during training.

### 2. Python owns episode bookkeeping

Python should own:

- reward computation
- policy inference
- `terminated` and `truncated` interpretation
- synchronization onto the next episode

Python `reset()` should wait for the next episode to begin. It should not be the thing that causes the in-game restart.

### 3. Non-blocking Lua loop

Lua should never block inside `MC_POST_UPDATE`.

Instead:

- keep a latched `last_action`
- poll TCP non-blockingly once per update tick
- if a new action arrives, replace `last_action`
- if no new action arrives, keep the old one
- apply the latched action on the action cadence

This avoids visible lag and keeps Isaac responsive even if Python is briefly slow.

### 4. One-way state stream

Lua should publish observations every decision tick without waiting for an immediate reply.

Per decision tick:

1. serialize current observation
2. send it to Python
3. poll non-blockingly for a fresh action or config command
4. latch any new action for the next tick

This is a better fit than strict request/response for a real-time game callback model.

### 5. Lua-owned terminal restart

When the episode ends, Lua should:

1. emit exactly one terminal observation
2. include terminal metadata
3. clear the current action
4. restart immediately
5. increment `episode_id`
6. begin sending observations for the new episode

This removes the fragile death-screen reset path entirely.

## Protocol Changes

### Lua -> Python

Each observation should include:

- `episode_id`
- `tick`
- `terminal`
- `terminal_reason`
- existing state payload

Example:

```json
{
  "episode_id": 17,
  "tick": 42,
  "terminal": false,
  "terminal_reason": null,
  "player_dead": false,
  "enemy_count": 1
}
```

Terminal reasons should include:

- `death`
- `room_cleared`
- `timeout`

### Python -> Lua

Keep commands minimal:

- `configure`
- `action`

`reset` should be removed from the training hot path. It can remain as a manual debug command if useful for ad hoc testing.

## Episode Lifecycle

### Normal tick

1. Lua sends observation
2. Lua polls for latest action non-blockingly
3. Lua latches action if present
4. Lua applies latched action on the next decision tick

### Terminal tick

1. Lua detects episode end
2. Lua sends one terminal observation
3. Python receives `terminated=True`
4. Lua restarts immediately
5. Lua increments `episode_id`
6. Python `reset()` waits until it sees a newer `episode_id`

### Python reset

Python `reset()` should:

1. finish any previous episode bookkeeping
2. wait for the first observation of a new `episode_id`
3. return that observation as the start of the next episode

## Why This Is Better

Compared with the current lockstep model:

- no socket read blocks Isaac's game thread
- death screens stop being special-case control flow
- Python stalls degrade into stale-action reuse instead of full game freezes
- restart latency is minimized
- the protocol becomes easier to reason about

Compared with keeping Lua "pure":

- it is less abstract
- it is much better aligned with the fact that Lua owns the game clock

For this project, that tradeoff is worth it.

## Implementation Plan

### Phase 1: stabilize ownership

1. Remove training-time dependence on Python-driven `reset`
2. Move terminal restart ownership into Lua
3. Add `episode_id`, `terminal`, and `terminal_reason` to serialized state

### Phase 2: make transport non-blocking on Lua side

1. Add a non-blocking `pollAction()` API in `mod/tcp_server.lua`
2. Preserve blocking accept only where harmless
3. Fail fast on disconnect and fall back to neutral action

### Phase 3: update Lua control loop

1. Replace blocking `receiveAction()` in `MC_POST_UPDATE`
2. Add latched action state
3. Emit one terminal observation before immediate restart
4. Reset latched action on episode restart

### Phase 4: update Python env contract

1. Change `reset()` to synchronize on `episode_id`
2. Remove buffered-state drain and reset-resend workarounds
3. Keep `step()` focused on consuming the streamed observations
4. Log episode metadata for debugging

### Phase 5: validate

1. Verify continuous movement and shooting during training
2. Verify death causes one terminal observation and immediate restart
3. Verify room clear does the same
4. Pause Python briefly and confirm Isaac does not hard-freeze
5. Measure steps/sec before and after the redesign

## Non-Goals

Not part of the first pass:

- replacing TCP
- parallel Isaac instances
- reward redesign
- observation redesign beyond episode metadata
- large training-code refactors unrelated to runtime synchronization

## Recommended Next Step

Implement the redesign as one coherent change set from a clean runtime baseline.

Do not mix:

- Python-owned resets
- non-blocking Lua polling
- partial render-only workarounds

That hybrid design is what created the confusing failure modes.
