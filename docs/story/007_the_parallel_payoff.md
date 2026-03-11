# Day 7: The Parallel Payoff

## The Blocker That Wasn't

Parallel training was always the plan. One agent learning from one game instance was fine for debugging, but real throughput meant multiple Isaacs feeding experience into the same model simultaneously.

On Linux, that plan had a wall behind it: Proton. Every game instance meant another Proton prefix, another layer of Wine translation, another set of filesystem indirection to manage. We had already spent sessions fighting Proton's quirks for a single instance. Multiplying that by four was not an engineering challenge — it was a morale challenge.

The move to Windows in Day 3 was about speed. But it quietly removed this blocker too. Isaac runs natively on Windows. No translation layer. No prefix management. No wondering if instance two's Proton runtime would conflict with instance three's socket binding.

The question shifted from "how do we make this work" to "what's the lightest way to isolate instances."

## Sandboxie: The Tool We Almost Overlooked

The options for running multiple Isaac instances on Windows ranged from heavy to heavier: full VMs, Docker with GPU passthrough, user-profile switching. Each brought real overhead — memory duplication, disk images, GPU arbitration.

Sandboxie-Plus turned out to be the answer. It's not a VM. It doesn't virtualize hardware or run a separate kernel. It intercepts filesystem and registry writes at the userspace level and redirects them to a sandbox folder. Reads still hit the real filesystem. The game binary, Steam, the mod files — all shared. Only the writes (save files, config state, registry keys) get isolated.

This meant each Isaac instance:
- Shares the actual game installation (no disk duplication)
- Shares the mod folder (one copy, all workers read it)
- Gets its own save state and registry view
- Runs as a normal Windows process with near-zero overhead

Two commands to verify the concept:
```
Start.exe /box:IsaacWorker1 Steam.exe -applaunch 250900
Start.exe /box:IsaacWorker2 Steam.exe -applaunch 250900
```

Two Isaac windows. Same machine. No conflicts. Phase 0 done in under an hour.

## Wiring It Up

The integration was straightforward because the architecture was already right.

The Lua mod reads its TCP port from an environment variable: `ISAAC_RL_PORT`. Sandboxie's `/env:` flag injects environment variables per-sandbox. So worker 1 listens on 9999, worker 2 on 10000, worker 3 on 10001. No config files to copy, no mod code to fork.

On the Python side, SB3's `SubprocVecEnv` already expects a list of environment factories. Each factory creates an `IsaacEnv` pointed at a different port. The PPO learner collects rollouts from all workers in parallel, runs one gradient update, and distributes the improved policy back. Standard vectorized training.

The `GamePauseCallback` needed a small update — pause and resume now fan out across all workers via `env_method()`. The metrics callback moved episode logging to the main process so it stays visible even when environments run in subprocesses.

A launcher script handles the Sandboxie orchestration: spin up N sandboxes with staggered starts, wait for each TCP port to become reachable, then hand off to training.

## The Subtle Bugs

Two things we caught mid-session that would have silently degraded training quality.

First: all four workers were generating identical coin spawn patterns. Same seed, same `math.random()` sequence, same training data four times over. The fix was one line in `config.lua`:

```lua
math.randomseed(os.time() + tonumber(Config.INSTANCE_ID) * 1000)
```

Without this, multi-worker training is faster in wall-clock time, but you're wasting most of the diversity benefit. Four identical rollouts teach less than four different ones.

Second: the player always spawned near the bottom of the room. With random coin placement, coins that happened to spawn near the bottom got collected in a few steps, while coins at the top required crossing the entire room. The agent learned to hug the bottom wall because that's where the cheap rewards were. The fix was teleporting the player to the room center on every episode start — removing the spatial bias entirely.

Neither bug crashed anything. Both would have been invisible without watching the game windows side by side.

## The Numbers

First real multi-worker run: 4 workers on random coin navigation.

| | 1 worker | 4 workers |
|---|---|---|
| Timesteps/min | ~671 | ~3,728 |
| Game ticks/sec (per worker) | 23.6 | 22.6 |
| Wall time | 79.5 min | 135.1 min |

**5.6x throughput gain with 4 workers.** Better than linear scaling, though part of that came from bumping Cheat Engine speed from 5x to 10x between runs. Per-worker tick rate held steady at ~23 ticks/sec. The workers weren't bottlenecking each other. The GPU wasn't saturated. The system scaled because the components were genuinely independent.

## The Bigger Picture

On Linux, parallel training would have meant: set up multiple Proton prefixes, debug per-prefix Steam authentication, handle Wine socket quirks, manage separate filesystem trees, and hope nothing breaks when you scale past two instances. Every step would have been a session unto itself.

On Windows, the entire multi-instance stack — Sandboxie sandboxes, environment variable injection, TCP port routing, `SubprocVecEnv` integration — was one session of work. The game ran natively. The mod loaded without translation layers. The sockets worked the way sockets should work.

Sometimes the right engineering decision isn't about algorithms or architecture. It's about picking the platform where the boring stuff is actually boring.

## What's Next

The last piece of manual friction: game speed still requires Cheat Engine per-instance. And we've added a `start_run` command to the mod protocol so training can auto-start runs from the title screen — no more clicking through menus in four windows.

The system is close to fully automated: launcher spins up sandboxes, training connects and starts runs, workers feed rollouts, one model learns from all of them. The only human step left is attaching the speedhack.
