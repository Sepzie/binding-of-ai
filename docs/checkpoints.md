# Checkpoint Management

## Folder Structure

Each training run creates its own folder under `checkpoints/`:

```
checkpoints/
  20260310_143000_phase0b-nav_abc123/
    step_0050000.zip
    step_0050000.meta.json
    step_0100000.zip
    step_0100000.meta.json
    final_model.zip
    final_model.meta.json
  20260310_150000_phase1a_def456/
    ...
  legacy/                          # migrated pre-manager checkpoints
    ...
```

Run ID format: `<YYYYMMDD_HHMMSS>_<config_name>[_<wandb_short_id>]`

## Metadata Sidecars

Every checkpoint has a `.meta.json` file saved alongside it:

```json
{
  "run_id": "20260310_143000_phase0b-nav_abc123",
  "config_path": "configs/phase0b-nav.yaml",
  "config_name": "phase0b-nav",
  "git_commit": "b13ffe7",
  "timestamp": "2026-03-10T14:35:00.123456",
  "step": 50000,
  "reason": "periodic",
  "wandb_run_id": "abc123",
  "wandb_project": "binding-of-ai"
}
```

Possible `reason` values: `periodic`, `final`, `interrupted`, `crashed`.

## W&B Artifact Tracking

Each checkpoint is logged as a W&B **artifact reference** (the file itself is not uploaded — only a pointer to the local path). This gives you:

- Every checkpoint linked to its W&B run in the UI
- Artifact collection per config: `<config_name>-checkpoint` (e.g. `phase0b-nav-checkpoint`)
- Aliases: `latest`, `step-50000`, `final`, `interrupted`, `crashed`
- Full metadata attached to each artifact version

To browse: go to your W&B project > Artifacts tab > select the config collection.

## Resume Modes

```powershell
# Resume latest checkpoint from the SAME config file
.\scripts\launch_training.ps1 -Config configs\phase0b-nav.yaml -Resume latest

# Resume latest checkpoint from ANY config
.\scripts\launch_training.ps1 -Config configs\phase0b-nav.yaml -Resume latest-any

# Resume latest checkpoint (same config) that actually loads without error
.\scripts\launch_training.ps1 -Config configs\phase0b-nav.yaml -Resume latest-compatible

# Resume from a specific path
.\scripts\launch_training.ps1 -Config configs\phase0b-nav.yaml -Resume checkpoints\20260310_143000_phase0b-nav_abc123\final_model.zip
```

`latest` scoping by config name means you won't accidentally resume a `phase1a` checkpoint when training `phase0b-nav`.

## Retention

Periodic checkpoints use a rolling window — only the last 5 are kept per run. Final, interrupted, and crashed checkpoints are always kept.

## Migration

Pre-manager checkpoints (flat files in `checkpoints/`) can be migrated:

```powershell
# Preview what will be moved
.venv\Scripts\python.exe scripts\migrate_checkpoints.py --dry-run

# Actually migrate
.venv\Scripts\python.exe scripts\migrate_checkpoints.py
```

This moves all flat `.zip` files into `checkpoints/legacy/` with best-effort metadata extracted from filenames.

## Key Files

- `python/checkpoint_manager.py` — `CheckpointManager` class
- `python/train.py` — `ManagedCheckpointCallback`, resume logic
- `scripts/migrate_checkpoints.py` — legacy migration script
