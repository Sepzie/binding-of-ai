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
