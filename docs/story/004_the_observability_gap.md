# Day 4: The Observability Gap

## The Questions That Had No Answers

The session started with questions, not tasks.

"Are we logging the framerate anywhere?" "How do I compare runs?" "What actually changed between this run and the last one?"

These sound simple. They weren't. The training loop was functional — it ran, it learned, it saved checkpoints. But it was a black box from the outside. Reward went up or down, and we'd squint at console output trying to figure out why.

The problem wasn't that the system was broken. The problem was that we couldn't *see* the system.

## What We Were Missing

The speed diagnostics were already there in the code — `frames_dropped`, `step_latency`, `game_ticks_per_sec` — all computed per episode in `isaac_env.py` and logged to the console via `log.info()`. But console logs scroll by. You can't overlay two runs' frame drop patterns on a graph from `stdout`.

Meanwhile, wandb was connected and receiving data from SB3's built-in callback: reward curves, loss, entropy, clip range. The standard stuff. But nothing Isaac-specific. The metrics that would actually tell us "is the game running smoothly?" or "is the TCP link keeping up?" — those were vanishing into terminal history.

The gap was classic: we had instrumentation, and we had a dashboard, but they weren't connected.

## Bridging It

The fix was a small custom SB3 callback — `IsaacMetricsCallback`. It hooks into `_on_step()`, checks for episode boundaries (SB3's Monitor wrapper adds an `"episode"` key to `info` when an episode ends), and logs our custom metrics to wandb:

- `episode/frames_dropped` — how many game ticks the Lua mod reported as dropped
- `episode/avg_step_latency_ms` — mean latency per step across the episode
- `episode/instant_ratio` — fraction of steps where state was already buffered (latency < 1ms)
- `episode/game_ticks_per_sec` — actual game simulation speed

These are now charts on the dashboard, right alongside reward curves. If a run's reward suddenly plateaus and frame drops spike at the same moment, we'll see the correlation instead of guessing.

## The Run Management Problem

The other half of the observability gap was organizational. Wandb was collecting runs, but they had auto-generated names like `twilight-river-7`. Trying to find "that run where I tried higher entropy" meant clicking through each one and reading its config.

The fix was even simpler: conventions.

Every run now gets a descriptive name (`phase1a-high-entropy`, `phase1a-6enemies-lr1e4`) and phase tags (`["phase1a", "entropy-sweep"]`). These rules went into `CLAUDE.md` so they're enforced across sessions — any agent working on this codebase will name and tag runs before launching them.

Small discipline, large payoff. The wandb dashboard goes from a pile of mystery runs to a searchable experiment log.

## The Bigger Picture

The conversation naturally drifted to "what happens when we leave the sandbox?" The single-room training setup is comfortable — short episodes, controlled spawns, tight feedback loops. But the plan has five phases, and Phase 3 (floor navigation) is where everything changes:

- Episodes go from seconds to minutes
- The observation space needs a minimap branch
- Door transitions introduce complex state management
- Training speed becomes the bottleneck — you can't wait 10 minutes per episode and expect PPO to converge in reasonable time

The honest answer: we're not ready for that yet. And we know we're not ready *because* we can now see what's happening. The speed metrics will tell us exactly when the game loop is the bottleneck vs. the policy update vs. TCP transport. The run management conventions will let us compare curriculum experiments without losing track of what we tried.

## The Lesson

Observability isn't a feature you add after the system works. It's what tells you *whether* the system works.

We had a training loop that produced reward curves. That's not observability — that's the minimum viable output. Real observability means being able to ask "why did this run behave differently from that one?" and getting an answer from the data, not from memory.

The work today was small — one callback class, a few conventions in a markdown file. But it changed what questions we can answer. And in ML, the quality of your questions determines the quality of your experiments.

**You can't improve what you can't see.**
