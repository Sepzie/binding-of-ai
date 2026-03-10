# Day 6: The Checkpoint Mess

## Ninety Files, Zero Context

After a few days of sweeps and interrupted runs, the `checkpoints/` folder had become a graveyard. Ninety zip files, flat in a single directory, with no record of which config produced which model.

Names like `20260309_222724_isaac_rl_50000_steps.zip` told you the time and the step count. They did not tell you the config, the W&B run, the git commit, or whether this was the `phase0b-nav-fs3` run or the `phase1a` run that crashed ten minutes later.

The `--resume latest` flag was basically coin-flipping across experiments. It would grab the most recent file by timestamp, regardless of what generated it. Resume a navigation checkpoint into a combat config? Sure, why not.

This was survivable during early prototyping. It was not going to survive the next phase.

## What We Built

The fix was a `CheckpointManager` — a single class that owns the full checkpoint lifecycle.

Each training run now gets its own folder: `checkpoints/<timestamp>_<config_name>_<wandb_id>/`. Inside, every checkpoint sits next to a `.meta.json` sidecar recording config path, git commit, step count, save reason, and W&B run ID.

The key design choice: `--resume latest` is now scoped to the same config file. If you trained with `phase0b-nav-fs3.yaml`, resume finds the latest checkpoint that was also produced by `phase0b-nav-fs3.yaml`. No cross-contamination. If you actually want cross-config resume, `--resume latest-any` is explicit about it.

Each checkpoint also gets logged as a W&B artifact reference — not uploaded, just referenced. This links every model to its run in the W&B UI without the upload overhead. Aliases like `latest`, `final`, and `step-50000` make programmatic lookup possible later.

## What We Removed

The old `WandbCallback` from SB3's integration was saving its own duplicate copies alongside our `TimestampedCheckpointCallback`. Two systems, same directory, no coordination.

Now there is one system. The `CheckpointManager` handles saving, metadata, W&B artifact logging, and retention cleanup in one place. The old callback is gone.

## The Practical Difference

Before: a flat folder you had to mentally parse by timestamp to guess which experiment a model came from.

After: structured folders, machine-readable metadata, W&B lineage, and resume logic that cannot accidentally cross experiments.

A migration script handles the ninety legacy files — moves them to `checkpoints/legacy/` with best-effort metadata extracted from filenames.

## Why This Matters

Checkpoint management is not exciting infrastructure. But every time you lose track of which model came from which experiment, you lose the ability to reproduce or resume confidently. That cost compounds quietly.

This was the session where the project moved from "move fast, figure it out later" to "the basics are handled, go run experiments."
