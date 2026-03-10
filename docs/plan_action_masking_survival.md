# Plan: Action Masking + Survival Pretraining Phase

## Why We're Doing This

The agent isn't learning to dodge. It gets run over by Gapers without any evasion
instinct. The core problem: it's trying to learn movement, spatial awareness, AND
shooting simultaneously across a 45-action combo space (9 move x 5 shoot). Too much
to explore at once with random initialization.

The fix is a survival pretraining phase (phase0) where the agent's only job is to
stay alive. Shooting is masked out — the agent can only move. Once it learns to dodge,
we unmask shooting and move to phase1a with all the spatial/movement knowledge intact.

We use **action masking** (MaskablePPO from sb3-contrib) rather than changing the
action space shape between phases. This means:
- Same model architecture throughout all phases — seamless weight transfer via normal resume
- Masked actions get zero probability: no gradient, no meaningless patterns learned
- When unmasked, those weights are still at random init — agent learns shooting from scratch
- Scales naturally to future phases (mask bombs, items, etc. until relevant)

---

## Implementation Steps

### Step 1: Install sb3-contrib

```bash
pip install sb3-contrib
```

Add to requirements.txt.

### Step 2: Add action mask config to PhaseConfig

In `config.py`, add a field to `PhaseConfig`:

```python
mask_shoot: bool = False  # When True, mask all shoot actions except "don't shoot" (0)
```

### Step 3: Add action_masks() method to IsaacEnv

`MaskablePPO` expects the env to have an `action_masks()` method that returns a list
of boolean arrays — one per action head in MultiDiscrete.

In `isaac_env.py`:

```python
def action_masks(self) -> list[np.ndarray]:
    """Return valid action masks for each action head."""
    move_mask = np.ones(9, dtype=bool)  # all movement always valid

    if self.config.phase.mask_shoot:
        # Only allow "don't shoot" (action 0), mask out shoot directions 1-4
        shoot_mask = np.array([True, False, False, False, False], dtype=bool)
    else:
        shoot_mask = np.ones(5, dtype=bool)  # all shoot actions valid

    return [move_mask, shoot_mask]
```

### Step 4: Switch PPO to MaskablePPO in train.py

Replace:
```python
from stable_baselines3 import PPO
```
With:
```python
from sb3_contrib import MaskablePPO as PPO
```

MaskablePPO is a drop-in replacement for PPO — same hyperparameters, same callbacks,
same checkpoint format. The only difference is it calls `env.action_masks()` before
sampling actions.

**Important:** MaskablePPO uses `MlpPolicy`/`MultiInputPolicy` from sb3-contrib, not
from stable_baselines3. Verify the import works with our custom feature extractor.
If not, we may need to register it or use `policy_kwargs` to pass it in (likely works
the same way — test this).

### Step 5: Create configs/phase0-survival.yaml

```yaml
env:
  frame_skip: 1
  max_episode_steps: 1500  # shorter — can't win, just survive

reward:
  damage_dealt: 0.0      # can't shoot anyway
  enemy_killed: 0.0      # can't kill
  damage_taken: -10.0    # harsh penalty for getting hit
  room_cleared: 0.0      # impossible
  death: -50.0           # strong death penalty
  time_penalty: 0.0      # REMOVE time penalty — contradicts "stay alive"
  survival_bonus: 0.5    # primary signal: +0.5 per tick alive with enemies present

train:
  total_timesteps: 500000
  learning_rate: 0.0003
  n_steps: 2048
  batch_size: 64
  ent_coef: 0.02         # slightly higher entropy to encourage exploration of movement

phase:
  enemy_type: 10          # Gaper
  enemy_variant: 0
  enemy_count: 1          # start with just one
  spawn_enemies: true
  random_spawn_positions: true
  spawn_radius_min: 80.0
  spawn_radius_max: 160.0
  disable_shooting: true  # Lua side also disables (belt and suspenders)
  mask_shoot: true        # Python side masks shoot actions

wandb:
  enabled: true
  project: "binding-of-ai"
  run_name: "phase0-survival-1gaper"
  tags: ["phase0", "survival", "action-masking"]
```

### Step 6: Update phase1a config

Add `mask_shoot: false` explicitly (it's the default, but be clear):

```yaml
phase:
  mask_shoot: false
  disable_shooting: false
```

### Step 7: Verify resume works across phases

Test that a phase0 checkpoint loads cleanly into a phase1a run:
```bash
python train.py --config configs/phase1a.yaml --resume checkpoints/<phase0-checkpoint>.zip
```

Since the architecture is identical (same action space shape, same obs space, same
network), this should just work with normal `MaskablePPO.load()`. The only difference
is the mask changes — previously-frozen shoot weights become active.

---

## What Success Looks Like

**Phase 0 (survival):**
- Agent learns to move away from approaching Gapers
- `episode/length` increases over training (survives longer)
- `episode/damage_taken` decreases
- `reward/survival_bonus` dominates the reward breakdown
- Agent develops clear kiting/dodging behavior visible in gameplay

**Phase 1a (combat, resumed from phase0):**
- Agent retains dodging behavior from phase0
- Quickly learns to shoot (new action head, random init, but features are trained)
- Win rate climbs faster than training phase1a from scratch
- `reward/damage_dealt` and `reward/kills` appear alongside maintained survival skills

---

## Risks and Mitigations

**Risk: MaskablePPO doesn't work with our custom feature extractor**
- Mitigation: Test early in step 4. sb3-contrib's MultiInputPolicy should accept
  `policy_kwargs` the same way. If not, we may need to subclass their policy.

**Risk: Value function learns survival-only values, struggles when shooting is unmasked**
- Mitigation: The value head will need to readjust, but the feature extractor (CNN +
  player MLP) carries spatial awareness. Use a slightly higher learning rate for the
  first N steps of phase1a, or just accept a brief dip.

**Risk: Agent learns to run to corners and stay there**
- Mitigation: Gapers follow the player, so corners are actually bad (cornered = hit).
  If this happens, add a small penalty for being near walls, or spawn enemies from
  random positions so there's no safe spot.

---

## Future: Expanding Masks for Later Phases

The action masking pattern scales naturally:
- Phase 2 (pickups): could add a "use active item" action head, masked until the agent
  picks one up
- Phase 3 (navigation): could mask door-entry actions until room is cleared
- Phase 5 (items): mask item-choice actions until standing on a pedestal

Each phase unmasks new capabilities while preserving everything learned before.
