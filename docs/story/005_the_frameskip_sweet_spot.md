# Day 5: The Frame Skip Sweet Spot

## From Plan to Proof

This session started from the action masking survival plan.

The goal was practical: simplify the training setup enough to get measurable signal quickly. We were not trying to solve the full game. We were trying to answer a basic systems question first:

1. Can the agent actually control Isaac and learn in this pipeline?
2. Which frame skip gives us the best learning behavior for this phase?

So we set up a focused navigation smoke task and ran a three-way comparison: `frame_skip=1`, `frame_skip=3`, and `frame_skip=5`.

## The Three Runs

At first glance, the runs looked uneven in duration and dashboard step counts. That almost sent us down the wrong path. But after checking the actual run configs and logged timesteps, the picture became clear:

- We had comparable behavior traces for the same task family.
- W&B `Step` was logging event count, not always the training timestep we mentally mapped to.
- The right comparison came from run config plus `time/total_timesteps`, not from visual intuition alone.

Once aligned, the trend was obvious.

## What We Saw

The `frame_skip=3` run found the shortcut fastest. Episode length collapsed earlier, and reward-time behavior stabilized ahead of the others.

Visually, the behavior change was dramatic. Early on, Isaac moved like a fly: noisy, wandering, indecisive. Later, it looked like a track runner: spawn, orient, sprint to coin, done.

This is the classic RL pattern of objective exploitation. The formal terms are `reward hacking` or `specification gaming`: the agent learns the quickest strategy to maximize the reward function we gave it.

In this phase, that was exactly what we wanted. The point was to verify control and learning dynamics, not to prevent exploitation yet.

## Why This Worked

The biggest win was observability discipline.

Because runs were tagged and visible in W&B with episode and reward metrics, we could move from "this feels faster" to "this converges earlier under comparable conditions." Without that setup, we would have been guessing from terminal scrollback and memory.

The session also produced process artifacts, not just a conclusion:

- A persistent training learnings log (`docs/training_log.md`)
- A rule in `CLAUDE.md` requiring new fundamental training lessons to be recorded with evidence links and confidence notes

## Current Takeaway

For the phase0b navigation coin-smoke setup, `frame_skip=3` is the current best operating point.

Not final truth, but a strong working default.

And the next scientific step is clear: run longer horizons in future sweeps to confirm that the ranking (`fs3` over `fs1` and `fs5`) holds under bigger training budgets.
