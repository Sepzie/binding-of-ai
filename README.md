# Binding of AI

A reinforcement learning agent that learns to play *The Binding of Isaac: Repentance* through curriculum-based training. A Lua mod inside the game communicates with a Python PPO trainer over TCP, streaming observations and receiving actions at 30 Hz.

This project also serves as a case study for a YouTube documentary series — development stories live in `docs/story/`.

## Architecture

```
Isaac (Lua Mod, 30 Hz)  ──TCP:9999──  Python (PPO via Stable-Baselines3)
```

The Lua mod owns the game clock. It serializes the room into an 8-channel grid + 14 player features, sends it over TCP as JSON, and polls non-blockingly for actions. Python's `IsaacEnv` (a Gymnasium wrapper) blocks on each state, computes rewards from state diffs, and feeds everything into SB3's PPO.

Lua never waits for Python — if Python is slow, the last action is re-applied. Python syncs across episode boundaries via `episode_id`. See [docs/archive/system_architecture.md](docs/archive/system_architecture.md) for a full diagram.

## Quick Start

### 1. Install the mod

```powershell
.\scripts\install_mod.ps1
```

This symlinks `mod/` into Isaac's mods directory. Use `-Method Copy` for a hard copy instead.

### 2. Set up Python

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r python\requirements.txt
```

### 3. Prepare Isaac

- Add `--luadebug` to Steam launch options
- Launch the game, enable **IsaacRL** from the Mods menu
- Verify the debug console shows `IsaacRL: Mod loaded`

### 4. Train

```powershell
.\scripts\launch_training.ps1 -Config configs\phase1a.yaml
```

Or directly:

```powershell
.venv\Scripts\python python\train.py --config configs\phase1a.yaml
```

### 4a. Parallel Launcher / TUI

For multi-instance runs, launch the worker manager first:

```powershell
.venv\Scripts\python python\launcher.py tui --workers 8 --batch-size 4
```

The TUI monitors worker windows and TCP readiness, and lets you launch batches,
send start sequences to selected workers, or terminate specific sandboxes.

For the headless worker flow, use:

```powershell
.venv\Scripts\python python\launcher.py launch --workers 8 --batch-size 4
```

### 5. Monitor

```powershell
tensorboard --logdir logs
```

Or enable [Weights & Biases](#weights--biases) in your config for richer experiment tracking.

### 6. Resume

```powershell
.\scripts\launch_training.ps1 -Config configs\phase1b.yaml -Resume latest
```

Resume modes: `latest`, `latest-compatible`, or a specific checkpoint path.

## Observation & Action Space

**Observations** (`Dict`):

| Component | Shape | Description |
|-----------|-------|-------------|
| `grid` | `(8, 7, 13)` | 8-channel spatial grid — walls, obstacles, pits, player, enemies (normalized HP), projectiles, pickups, doors |
| `player` | `(14,)` | HP (red/soul/black), speed, damage, range, fire rate, shot speed, luck, bombs, keys, coins, active item, charge |

**Actions** (`MultiDiscrete([9, 5])`):

- **Move (0-8)**: idle, 4 cardinal, 4 diagonal
- **Shoot (0-4)**: none, up, down, left, right

## Reward Shaping

Rewards are computed from state diffs each tick:

| Component | Default | Trigger |
|-----------|---------|---------|
| `damage_dealt` | +1.0 | Per HP of damage dealt to enemies |
| `enemy_killed` | +5.0 | Per enemy eliminated |
| `damage_taken` | -10.0 | Each time the player loses HP |
| `room_cleared` | +20.0 | All enemies in the room are dead |
| `death` | -50.0 | Player dies |
| `time_penalty` | -0.1 | Every tick (encourages speed) |
| `survival_bonus` | 0.0 | Per tick while enemies remain (optional) |

All weights are configurable per phase via YAML.

## Training Curriculum

Training follows a curriculum of increasing difficulty (see [CHECKLIST.md](CHECKLIST.md)):

| Phase | Config | Goal |
|-------|--------|------|
| **1a** | `phase1a.yaml` | Kill Gapers — learn to aim and shoot |
| **1b** | `phase1b.yaml` | Kill Monstro — learn to dodge projectiles |
| **1c** | `phase1c.yaml` | Multiple mixed enemies — prioritization, kiting |
| **2** | `phase2.yaml` | Room combat with pickups |
| **3** | `phase3.yaml` | Single floor navigation |
| **4** | `phase4.yaml` | Multi-floor runs (Basement to Mom) |

Each phase resumes from the previous checkpoint to transfer learned behavior.

## Configuration

Configs are YAML files with five sections:

```yaml
env:
  frame_skip: 1              # Send state every Nth game tick
  max_episode_steps: 3000    # Episode timeout

reward:
  damage_dealt: 1.0
  enemy_killed: 5.0
  death: -50.0
  # ... all weights configurable

train:
  learning_rate: 0.0003
  total_timesteps: 1000000
  save_interval: 50000       # Checkpoint frequency

phase:
  enemy_type: 10             # Isaac EntityType (10=Gaper)
  enemy_count: 4
  spawn_enemies: true

wandb:
  enabled: false
  project: "binding-of-ai"
```

See [configs/phase1a.yaml](configs/phase1a.yaml) for a complete example.

## Checkpoints

- Saved to `checkpoints/` every `save_interval` steps with timestamped filenames
- Ctrl+C saves an `interrupted_model` checkpoint before exiting
- Crashes save a `crashed_model` checkpoint
- Resume with `--resume latest`, `--resume latest-compatible`, or a specific path

## Weights & Biases

Enable experiment tracking by setting `wandb.enabled: true` in your config YAML. First-time setup:

```powershell
wandb login
```

Logs all hyperparameters, PPO metrics, and model checkpoints to your W&B dashboard.

## Speed Diagnostics

The environment tracks timing metrics to help tune the speed multiplier:

- **Frame drops**: Detected via `episode_tick` gaps between Lua and Python. If Python can't keep up with the game, frames are skipped.
- **Step latency**: Time Python spends waiting for each state. Low = game is the bottleneck. High = Python is faster than the game.
- Both are logged per episode: `frames_dropped=0 avg_latency=33.2ms`

## Project Structure

```
binding-of-ai/
├── mod/                    # Lua mod (runs inside Isaac)
│   ├── main.lua            # Episode lifecycle, frame skip
│   ├── state_serializer.lua# 8-ch grid + 14 player features
│   ├── action_injector.lua # Input interception
│   ├── game_control.lua    # Enemy spawning, resets
│   ├── tcp_server.lua      # TCP server (JSON lines)
│   └── config.lua          # Mod defaults
├── python/                 # Python training code
│   ├── train.py            # Main training loop
│   ├── isaac_env.py        # Gymnasium environment
│   ├── reward.py           # Reward shaping
│   ├── network.py          # CNN+MLP feature extractor
│   ├── config.py           # Config dataclasses
│   ├── evaluate.py         # Model evaluation
│   └── utils.py            # Checkpoint utilities
├── configs/                # YAML configs per curriculum phase
├── scripts/                # PowerShell helpers
│   ├── install_mod.ps1     # Mod installation
│   └── launch_training.ps1 # Training launcher
├── checkpoints/            # Saved models (auto-created)
├── logs/                   # TensorBoard events (auto-created)
└── docs/
    ├── archive/            # Architecture diagrams, old plans
    └── story/              # Documentary case-study writeups
```

## Requirements

- Windows 10+ with Steam
- The Binding of Isaac: Repentance
- Python 3.9+
- `--luadebug` Steam launch option
