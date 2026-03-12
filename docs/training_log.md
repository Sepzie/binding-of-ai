# Training Log

This file captures durable lessons from training runs so we can reuse what we learn.

## 2026-03-10 - Phase0b nav coin smoke frame-skip sweep
- Takeaway: `frame_skip=3` is the current sweet spot for learning speed and stability in this task setup.
- RL term: this behavior is commonly called `reward hacking` or `specification gaming` (the agent learns a shortcut that maximizes the specified reward efficiently).
- Evidence:
  - fs1 baseline (`phase0b-nav-coin-smoke`): https://wandb.ai/sepzie1/binding-of-ai/runs/8d74tvnm
  - fs3 (`phase0b-nav-coin-smoke-fs3`): https://wandb.ai/sepzie1/binding-of-ai/runs/0eean4d5
  - fs5 (`phase0b-nav-coin-smoke-fs5`): https://wandb.ai/sepzie1/binding-of-ai/runs/08h2ljsi
- Observed pattern:
  - fs3 reaches short-episode/high-reward behavior earlier than fs1 and fs5.
  - fs5 improves too, but converges later in W&B step-space and has slower env-step throughput at equal timesteps.
- Confidence: medium-high.
- Follow-up: run longer training budgets in future sweeps to confirm this ranking persists at larger timestep counts.

## 2026-03-12 - PPO hyperparameter tuning (phase0c multicoin)

- **Takeaway:** Default SB3 PPO settings were far too aggressive for our setup. Tuning `target_kl`, `clip_range`, and `learning_rate` dramatically improved training stability and reward.
- Evidence:
  - Before tuning (default-ish settings, lr=3e-4, n_epochs=10): clip_fraction ~0.5, approx_kl 0.10-0.15, reward oscillated wildly between runs. Run: https://wandb.ai/sepzie1/binding-of-ai/runs/kob9gwks
  - After tuning (lr=5e-5, clip_range=0.1, target_kl=0.03, n_epochs=4, batch_size=256, n_steps=2048): clip_fraction 0.20-0.40, approx_kl 0.02-0.05, explained_variance 0.75-0.85, smooth reward curve 50→100. Run: https://wandb.ai/sepzie1/binding-of-ai/runs/d8meaq3c
- Key metrics to watch:
  - `clip_fraction`: healthy range 0.1-0.2, above 0.3 means policy is changing too aggressively
  - `approx_kl`: healthy range 0.01-0.03, above 0.05 means updates are too large
  - `explained_variance`: should trend toward 0.8-1.0, below 0.5 means value function is struggling
  - `target_kl` is the most surgical lever — it early-stops epoch updates when KL exceeds threshold, preventing overshoot
- Confidence: high.
- Follow-up: clip_fraction is still 0.2-0.4 (ideally <0.2). Could try further reducing lr or increasing batch size if it becomes a bottleneck again.

## 2026-03-12 - Single-coin reward design limitations

- **Takeaway:** A large binary reward (+50 for coin pickup) with tiny time penalty (-0.03/step) creates a nearly binary reward signal. The model learns to reach the coin but has little gradient to optimize *speed* of collection.
- Solution: switched to multicoin respawn setup (coins respawn on pickup, +5.0 per coin, -0.05/step time penalty, 500-step timeout). This gives continuous reward signal proportional to collection efficiency.
- Confidence: high — reward mean went from ~60 (single coin) to ~100 (multicoin, ~20 coins/episode).

## 2026-03-12 - Observation resolution and wall-sticking

- **Takeaway:** The 7x13 grid observation is too coarse for precise navigation near room edges. Isaac and pickups exist at continuous positions but are quantized to discrete grid cells. When a coin is slightly above Isaac near the bottom wall, the model can't distinguish the small offset and gets stuck.
- Observed: Isaac frequently gets stuck running into walls when coins are just barely offset from its position, especially near room boundaries.
- Candidate fixes (untested):
  1. Add continuous player position + nearest pickup position to the player vector (cheap, targeted)
  2. Double grid resolution to 14x26 (expensive, general improvement)
- Confidence: medium — the wall-sticking pattern is consistent, but haven't confirmed it's purely an observation issue.
- Follow-up: try adding continuous positions to player vector first as the cheaper experiment.

## 2026-03-12 - Resuming from checkpoints with different hyperparameters

- **Takeaway:** When resuming training from a checkpoint with different config, several SB3 internals need manual fixup:
  1. `clip_range` must be wrapped in `constant_fn()` — SB3 expects a callable schedule, not a raw float.
  2. `n_steps` change requires recreating the rollout buffer — `PPO.load()` allocates the buffer at load time with the old size.
  3. Old checkpoint hyperparameters (value function quality, etc.) don't poison the new run — after ~100k+ steps, the model fully adapts to new settings.
- Confidence: high — hit both bugs in practice and confirmed fixes.
