# Day 8: The Ghost in the Graph

## The Regression That Wasn't

We had just finished parallel training. Four workers, 10x game speed, 5.6x throughput gain. The system was faster than it had ever been. So we ran the same smoke test that had validated everything in Day 5: navigate to a coin in a locked room. A solved problem.

The new run flatlined at -6.0 reward. Every episode timed out. No learning at all.

The original run — one worker, 5x speed, 3.5k steps on the W&B x-axis — had converged beautifully. The new run was already past 8k steps and showed nothing. Same config, same task, objectively better infrastructure. Worse results.

The instinct was to blame the frame drops.

## The Frame Drop Hypothesis

The multi-worker setup introduced a new artifact: periodic frame drops. During PPO gradient updates, the Python side goes silent for a burst of time — no actions sent, no states consumed. At 10x game speed with four workers, this meant the Lua game loop would advance 30–50 frames with no agent input, replaying the last action or doing nothing.

The old single-worker 5x setup never dropped a frame. Zero. The timing was gentle enough that Python always responded before the next game tick.

This was a reasonable suspect. Frame drops mean the agent's experience buffer contains corrupted transitions — the state changes during the gap, but the agent's record doesn't reflect it. Reward attribution breaks. The learning signal turns to noise.

But before fixing anything, we looked more carefully at the graphs.

## The Ghost

Both runs were labeled `phase0b-nav-coin-smoke-fs3`. Both had an x-axis labeled "Step" in W&B. But one showed 3.5k steps over 80 minutes. The other showed 16k steps in 8 minutes.

That ratio didn't make sense under any performance improvement. 10x speed and 4x workers gives maybe 20x throughput. Not 400x.

The difference was in what "Step" meant.

The original run used `wandb.log(metrics)` — no explicit step. W&B auto-increments an internal counter: one call, one step. Each call happened once per episode. So the x-axis was **episode count**, not timesteps.

The new code used `wandb.log(metrics, step=self.num_timesteps)` — explicitly setting the step to the PPO environment step counter. The x-axis was now **timesteps**.

The 3.5k "steps" in the old run were 3,500 episodes. At roughly 10 steps per converged episode, that was around 35,000 actual timesteps — nearly the full training budget of 40,000. The old run didn't converge at step 200. It converged at episode 200, which was thousands of timesteps in.

The new run's 16k "steps" were 16,000 timesteps out of 100,000. It was less than halfway through training. The comparison was meaningless. We were reading a ghost — a visual artifact of the axis change, not a real regression.

## The Real Fix

The frame drops were still real, and still worth fixing. At high game speed, if Lua doesn't have a fresh action from Python, the right behavior is to **stall** — hold the game loop until the action arrives, rather than advancing blind. This is the lock-step protocol: no action, no tick.

But we ran the first test at 5x speed with a single worker to isolate variables. Zero frame drops, clean timing. The training converged. Not just to parity with the old run — it was actually smoother, because the explicit `step=self.num_timesteps` meant W&B was tracking real training progress instead of episode count proxied through auto-increment.

Then we ran with four workers. Same convergence. Faster wall-clock time. The infrastructure improvements were real.

## The Lesson

Observability tools don't just need to exist. They need to mean the same thing across runs.

When we changed the W&B step semantics, the dashboard became more accurate — timesteps is the right x-axis for comparing training across different configurations, worker counts, and episode lengths. But the change also made every previous run visually incompatible. The old graphs looked like instant convergence. The new graphs looked like failure. Neither impression was true.

The temptation was to chase a performance bug. The reality was a units mismatch.

**Same metric, different ruler. That's enough to see a ghost.**
