# Parallel Isaac Instances Plan

## Goal

Increase rollout throughput by running multiple live Isaac environments in parallel on one machine, without introducing timer hacks or changing game speed.

This plan covers both sides of the problem:

- game-side process isolation under Steam/Proton
- repo-side runtime, IPC, and trainer changes needed to use multiple workers

## Why This Path First

Parallel instances are the highest-leverage next step because:

- the current single instance is light on CPU and RAM
- multiple normal-speed environments are safer than one accelerated environment
- PPO benefits directly from more rollout streams
- the main risks are operational and architectural, not engine-timing hacks

## Current State

The current implementation assumes exactly one game instance:

- fixed TCP port `9999` in `mod/config.lua` and `python/config.py`
- fixed fallback IPC filenames in `/tmp`
- one `TcpServer` in the Lua mod
- one `IsaacEnv` in `python/train.py`
- one shared `checkpoints/` directory
- one shared `logs/` directory
- mod install path assumes the default Proton prefix for app `250900`

The current code is therefore single-instance by construction, but those are straightforward engineering constraints. The harder problem is launching more than one Isaac process cleanly.

## Core Question

Can The Binding of Isaac run as multiple simultaneous Proton processes on the same machine?

The working assumption is:

- do not ask Steam to launch the game twice
- keep Steam running once
- launch additional Isaac workers manually through Proton
- give each worker its own `STEAM_COMPAT_DATA_PATH`

This uses one shared game install and one shared Steam client, while isolating each worker's Proton prefix, save paths, mods, and config files.

## Architecture Decision

### Recommended model

Use one learner process and `N` Isaac workers.

Each worker gets:

- its own Proton compatdata directory
- its own TCP port
- its own temp directory
- its own instance id
- its own run-scoped logs

The learner process gets:

- one vectorized environment made from `N` `IsaacEnv` instances
- one policy model
- one checkpoint stream

### Deferred model

Do not use Docker in the first implementation.

Docker does not solve the hard parts:

- Steam and Proton still need host GPU and display integration
- Isaac still needs per-worker prefix isolation
- multiple GUI game processes inside containers are harder to operate and debug
- container overhead is not the main concern, operational complexity is

Docker can be reconsidered later if there is a proven need for:

- reproducible deployment across machines
- worker placement across multiple hosts
- remote orchestration

## Game-Side Plan

### Phase 0: prove that multiple Isaac processes are possible

Before changing training code, prove the launch model manually.

Objective:

- start a second Isaac process while the first is already running
- use a different compatdata directory for the second instance
- confirm both processes remain alive at the same time

Required worker-specific launch inputs:

- `STEAM_COMPAT_DATA_PATH`
- `STEAM_COMPAT_CLIENT_INSTALL_PATH`
- `STEAM_COMPAT_INSTALL_PATH`
- `STEAM_COMPAT_LIBRARY_PATHS`
- `SteamAppId=250900`
- `SteamGameId=250900`

Success criteria:

- worker 2 starts without killing worker 1
- worker 2 reaches menu or gameplay
- worker 2 writes to its own prefix instead of the default prefix

Failure modes to expect:

- Steam or the game enforces a single-instance mutex
- Steam overlay or Steam API attachment fails on worker 2
- worker 2 launches but immediately exits
- both workers share state unexpectedly because prefix isolation is incomplete

If Phase 0 fails, stop and reassess before modifying training code.

### Phase 1: define worker prefix layout

Adopt a deterministic directory structure for manual and scripted launches.

Suggested layout:

```text
runtime/
  workers/
    worker-01/
      compatdata/
      tmp/
      logs/
    worker-02/
      compatdata/
      tmp/
      logs/
```

Each worker prefix should own:

- `Documents/My Games/Binding of Isaac Repentance/...`
- `mods/`
- `options.ini`
- Wine prefix state

Important constraint:

- `options.ini` may only be edited while the game is closed

### Phase 2: decide windowing strategy

Plan for headful operation first.

Recommended first pass:

- run workers windowed
- keep them visible or placed on a secondary workspace
- avoid trying to make them fully hidden until basic multi-instance stability is proven

Why:

- hidden or virtual displays introduce another layer of uncertainty
- windowed mode is operationally simpler during debugging
- performance is still likely good enough for the first throughput win

Future options:

- virtual X server or nested compositor
- tighter window placement automation
- per-worker display routing if needed

### Phase 3: mod deployment strategy

Every worker must see the same mod code, but through its own prefix.

Recommended approach:

- keep one source mod directory in the repo
- link or copy that mod into each worker's prefix-specific Isaac mods directory

This ensures:

- identical game logic across workers
- worker prefixes remain isolated
- mod updates remain centralized

## Repo-Side Plan

### Phase 4: remove transport singletons

Parameterize the transport layer so each worker has independent endpoints.

Lua mod changes:

- read host from env or generated config
- read port from env or generated config
- read instance id from env or generated config
- namespace fallback file IPC paths by instance id

Python changes:

- support per-worker host and port in config
- make `IsaacEnv` instance-aware for logging and diagnostics

At the end of this phase, two workers should be able to run the same codebase without transport collisions.

### Phase 5: add worker launch orchestration

Create a dedicated launcher for multi-worker runs.

Responsibilities:

- create worker runtime directories
- prepare compatdata paths
- install or link the mod into each worker prefix
- assign unique ports
- assign unique temp dirs
- launch worker game processes
- wait for workers to become reachable
- shut workers down cleanly

This launcher is the correct place to encode the Proton launch contract. It should not be spread across ad hoc shell commands and trainer internals.

### Phase 6: convert training to vectorized environments

Replace the single-env training path with a vectorized env setup.

Target structure:

- one `IsaacEnv` per worker
- `SubprocVecEnv` or `DummyVecEnv` depending on stability
- PPO learns from the combined rollout batch

Recommended first pass:

- use `SubprocVecEnv` with `2` workers
- keep policy inference and learning in one main process

Key trainer changes:

- build env factories from a worker manifest
- send per-worker configure messages at startup
- namespace worker logs
- aggregate throughput metrics across workers

### Phase 7: make outputs run-scoped

Training outputs must stop assuming one global run.

Change the trainer to support:

- run-specific checkpoint directories
- run-specific TensorBoard directories
- worker-specific log files where useful

This avoids collisions between:

- single-worker and multi-worker runs
- restarts of the same experiment
- multiple active experiments

### Phase 8: improve observability

Multi-instance systems fail in more ways than single-instance systems. Add enough telemetry to diagnose them quickly.

Add:

- worker id in Lua console messages
- worker id in Python env logs
- per-worker connection status
- per-worker steps/sec
- per-worker terminal reason counts
- launch-time capture of each worker's prefix, port, and pid

## Proposed Implementation Sequence

### Milestone 1: viability only

Deliverables:

- manual proof that two Isaac instances can coexist
- documented launch contract for worker 2

Do not change the trainer yet.

### Milestone 2: instance-aware runtime

Deliverables:

- env-driven instance id, port, and temp dir
- mod file IPC namespaced by worker
- launcher capable of starting multiple workers

Still acceptable at this stage:

- one learner talking to only one worker at a time
- manual validation instead of full PPO rollout

### Milestone 3: two-worker training

Deliverables:

- vectorized training with two workers
- isolated logs and checkpoints
- stable startup and shutdown path

Success metric:

- throughput improvement over one worker is measurable and repeatable

### Milestone 4: scale-up evaluation

Test:

- `N=2`
- `N=3`
- `N=4`

Measure:

- environment steps/sec
- PPO update time
- GPU utilization
- game stability
- restart reliability

Stop scaling when:

- marginal throughput gain drops sharply
- compositor or Proton instability rises
- trainer becomes the bottleneck

## Technical Risks

### Highest risk

- Isaac or Steam may enforce single-instance behavior even with separate prefixes

### Medium risk

- multiple Proton windows may create compositor overhead or focus/input weirdness
- worker startup may be slow because prefix initialization is expensive
- one worker may wedge while others continue, requiring watchdog logic

### Lower risk

- transport collisions after parameterization
- checkpoint or log path collisions
- Lua mod deployment inconsistencies between worker prefixes

## Validation Checklist

### Game-side validation

- two Isaac processes exist simultaneously
- each worker uses its own compatdata directory
- each worker has its own `options.ini`
- each worker loads the RL mod
- restarting one worker does not affect the other

### Runtime validation

- worker 1 and worker 2 bind different ports
- trainer can connect to both workers independently
- episode ids progress independently per worker
- disconnecting one worker is observable and recoverable

### Training validation

- PPO collects rollouts from both workers
- aggregate steps/sec exceeds single-worker baseline
- reward logging remains coherent
- checkpoints save and resume correctly

## Explicit Non-Goals

Not part of the first parallel-instance pass:

- time-scaling or speedhack support
- Dockerized Isaac workers
- cross-machine distributed rollout collection
- observation-space redesign
- reward redesign
- headless rendering research

## Recommendation

Proceed in this order:

1. prove two concurrent Isaac Proton processes are possible with separate compatdata directories
2. parameterize the runtime so workers do not collide on ports or temp files
3. build a dedicated multi-worker launcher
4. convert training to vectorized PPO
5. measure scaling before considering more exotic isolation or acceleration

The gating insight is simple:

- if manual two-instance launch is impossible, no amount of trainer refactoring matters
- if manual two-instance launch works, the remaining work is normal engineering
