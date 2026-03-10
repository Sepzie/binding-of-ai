# Parallel Isaac Instances Plan (Windows / Sandboxie-Plus)

## Goal

Increase rollout throughput by running multiple live Isaac environments in parallel on one machine, without introducing timer hacks or changing game speed.

## Why This Path First

Parallel instances are the highest-leverage next step because:

- the current single instance is light on CPU and RAM
- multiple normal-speed environments are safer than one accelerated environment
- PPO benefits directly from more rollout streams
- the main risks are operational and architectural, not engine-timing hacks

## Current State

The current implementation assumes exactly one game instance:

- fixed TCP port `9999` in `mod/config.lua` and `python/config.py`
- fixed fallback IPC filenames in temp dir (dead code — luasocket works)
- one `TcpServer` in the Lua mod
- one `IsaacEnv` in `python/train.py`
- one shared `checkpoints/` directory (already per-run via CheckpointManager)
- one shared `logs/` directory

## Platform: Windows + Sandboxie-Plus

### Why Sandboxie

Previous plan (`parallel_instances_plan.md`) targeted Linux/Proton. The project now runs on Windows natively. Sandboxie-Plus provides lightweight process isolation without VMs:

- **Not a VM**: processes run on the real OS with native GPU access
- **Filesystem virtualization**: reads go to the real filesystem, writes are redirected to a per-sandbox folder
- **Minimal overhead**: ~MBs per sandbox (only redirected writes), no OS duplication
- **Steam compatibility**: each sandbox sees its own Steam state, avoids singleton detection
- **Network**: localhost/loopback works by default across sandboxes

### Phase 0: Prove multi-instance viability — DONE

Two Isaac instances run simultaneously via Sandboxie-Plus:

- `IsaacWorker1` and `IsaacWorker2` sandboxes created
- Both instances launch, reach gameplay, and run side by side
- No Steam conflicts, no mutex issues
- File access rules grant each sandbox open access to:
  - `C:\Program Files (x86)\Steam\*`
  - `C:\Projects\binding-of-ai\*`
  - `C:\Users\Sepehr\Documents\My Games\Binding of Isaac Repentance\*`

### Sandbox Setup (for additional workers)

1. In Sandboxie-Plus: right-click → Duplicate Sandbox (from IsaacWorker1)
2. Rename to `IsaacWorkerN`
3. Launch: right-click sandbox → Run Program → `C:\Program Files (x86)\Steam\steam.exe`
4. Isaac launches via Steam inside the sandbox

## Architecture

### One learner, N workers

```
┌─────────────────────────────────────┐
│           Python Learner            │
│                                     │
│  ┌──────────┐  ┌──────────┐        │
│  │IsaacEnv 1│  │IsaacEnv 2│  ...   │
│  │ port 9999│  │port 10000│        │
│  └────┬─────┘  └────┬─────┘        │
│       │              │              │
│  SubprocVecEnv / DummyVecEnv        │
│           │                         │
│       PPO model (single)            │
└───────────┼─────────────────────────┘
            │
    ┌───────┴───────┐
    │               │
┌───┴────┐   ┌─────┴──┐
│Sandbox1│   │Sandbox2│   ...
│Isaac   │   │Isaac   │
│Lua mod │   │Lua mod │
│TCP 9999│   │TCP10000│
└────────┘   └────────┘
```

Each worker gets:
- its own Sandboxie sandbox
- its own TCP port (assigned via env var `ISAAC_RL_PORT`)
- its own instance ID (env var `ISAAC_RL_INSTANCE`)

The learner gets:
- one vectorized environment wrapping N `IsaacEnv` instances
- one PPO policy model
- one checkpoint stream

All workers train the **same model** — PPO collects rollouts from all workers, batches them, and does one combined policy update.

## Implementation Plan

### Phase 1: Parameterize transport layer

**Lua mod changes** (`mod/config.lua`, `mod/tcp_server.lua`):
- Read `ISAAC_RL_PORT` from environment variable
- Fall back to default 9999 if not set
- Read `ISAAC_RL_INSTANCE` for log prefixing
- Log the actual port on startup for debugging

**Python changes** (`python/config.py`):
- `EnvConfig` already supports `port` — no structural change needed
- Launcher will create per-worker configs or override port programmatically

**File IPC fallback**: ignore. It's dead code (luasocket works). Sandboxie isolates temp writes per sandbox anyway.

After this phase: two workers can run the same mod code without port collisions.

### Phase 2: Launcher script

Create `python/launcher.py` that:
- Accepts number of workers as argument
- For each worker:
  - Sets `ISAAC_RL_PORT` and `ISAAC_RL_INSTANCE` env vars
  - Launches Steam+Isaac inside the appropriate sandbox via Sandboxie CLI:
    `Start.exe /box:IsaacWorkerN /env:ISAAC_RL_PORT=<port> "C:\Program Files (x86)\Steam\steam.exe" -applaunch 250900`
  - Optionally automates entering a run (via mod auto-start or key simulation)
- Waits for all workers to become reachable on their TCP ports
- Provides clean shutdown (terminate sandbox processes)

### Phase 3: Vectorized training

Replace single-env training with vectorized setup:
- Create N `IsaacEnv` instances, each configured with a different port
- Wrap in SB3's `SubprocVecEnv` (or `DummyVecEnv` for debugging)
- PPO learns from the combined rollout batch
- `n_steps` in config applies per-worker (total batch = n_steps × n_workers)

Key trainer changes:
- Build env factories from worker manifest (list of ports)
- Send per-worker configure messages at startup
- Aggregate throughput metrics across workers

### Phase 4: Observability

- Worker ID in Lua console messages
- Worker ID in Python env logs
- Per-worker connection status and steps/sec
- Per-worker episode counts in W&B

## Proposed Implementation Sequence

### Milestone 1: Port parameterization (Phase 1)
- Env var support in Lua mod
- Manual test: two instances on different ports, both connecting to Python

### Milestone 2: Automated launch (Phase 2)
- Launcher script with Sandboxie CLI integration
- Scripted startup of N workers

### Milestone 3: Two-worker training (Phase 3)
- Vectorized PPO with 2 workers
- Throughput improvement measurable over single worker

### Milestone 4: Scale-up evaluation
- Test N=2, 3, 4
- Measure: env steps/sec, PPO update time, GPU utilization, stability
- Stop scaling when marginal throughput drops or instability rises

## Technical Risks

### Highest risk
- Sandboxie may interfere with luasocket binding (test in Phase 1)
- Steam updates inside sandbox may cause unexpected state

### Medium risk
- Multiple game windows may cause focus/input issues
- Worker startup time may be slow (Steam init per sandbox)
- One worker may wedge while others continue — needs watchdog logic

### Lower risk
- Transport collisions after parameterization (straightforward)
- Checkpoint or log path collisions (already per-run)

## Explicit Non-Goals

Not part of the first parallel-instance pass:

- time-scaling or speedhack support
- VM-based isolation
- cross-machine distributed rollout collection
- observation-space or reward redesign
- headless rendering
- removing the file IPC dead code
