"""Checkpoint management with per-run folders, metadata sidecars, and W&B artifact tracking."""

import json
import logging
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger("checkpoint_manager")


def _git_commit_short() -> str | None:
    """Return the short git commit hash, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


class CheckpointManager:
    """Manages checkpoint saving, metadata, folder structure, and W&B artifact logging.

    Folder layout:
        checkpoints/<run_id>/
            step_050000.zip
            step_050000.meta.json
            final_model.zip
            final_model.meta.json

    run_id format: <YYYYMMDD_HHMMSS>_<config_name>[_<wandb_short_id>]
    """

    def __init__(
        self,
        base_dir: Path,
        config_path: str | None,
        config,
        wandb_run=None,
        max_periodic: int = 5,
    ):
        self.base_dir = Path(base_dir)
        self.config_path = config_path
        self.config_name = Path(config_path).stem if config_path else "default"
        self.config = config
        self.wandb_run = wandb_run
        self.max_periodic = max_periodic
        self.git_commit = _git_commit_short()

        # Build run_id
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wandb_suffix = f"_{wandb_run.id}" if wandb_run else ""
        self.run_id = f"{timestamp}_{self.config_name}{wandb_suffix}"

        # Create run directory
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        log.info("Checkpoint run dir: %s", self.run_dir)

    def save(self, model, name: str, step: int, reason: str) -> Path:
        """Save a checkpoint with metadata sidecar and optional W&B artifact.

        Args:
            model: The SB3 model to save.
            name: Checkpoint stem (e.g. 'step_050000', 'final_model').
            step: Current training timestep.
            reason: One of 'periodic', 'final', 'interrupted', 'crashed'.

        Returns:
            Path to the saved .zip file.
        """
        checkpoint_path = self.run_dir / name
        model.save(str(checkpoint_path))
        zip_path = checkpoint_path.with_suffix(".zip")

        # Write metadata sidecar
        meta = {
            "run_id": self.run_id,
            "config_path": self.config_path,
            "config_name": self.config_name,
            "git_commit": self.git_commit,
            "timestamp": datetime.now().isoformat(),
            "step": step,
            "reason": reason,
            "wandb_run_id": self.wandb_run.id if self.wandb_run else None,
            "wandb_project": self.wandb_run.project if self.wandb_run else None,
        }
        meta_path = self.run_dir / f"{name}.meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        # Log W&B artifact reference
        if self.wandb_run:
            self._log_artifact(zip_path, meta, reason)

        # Enforce rolling window for periodic checkpoints
        if reason == "periodic":
            self._cleanup_periodic()

        log.info("Saved %s checkpoint: %s (step %d)", reason, zip_path.name, step)
        return zip_path

    def _log_artifact(self, zip_path: Path, meta: dict, reason: str):
        """Log a checkpoint as a W&B artifact reference (no upload)."""
        import wandb

        # Artifact collection name groups all checkpoints from this config
        artifact_name = f"{self.config_name}-checkpoint"
        artifact = wandb.Artifact(
            name=artifact_name,
            type="model",
            metadata=meta,
        )
        artifact.add_reference(zip_path.resolve().as_uri())

        # Build aliases
        aliases = [f"step-{meta['step']}"]
        if reason in ("final", "interrupted", "crashed"):
            aliases.append(reason)
        aliases.append("latest")

        self.wandb_run.log_artifact(artifact, aliases=aliases)

    def _cleanup_periodic(self):
        """Keep only the last N periodic checkpoints in this run directory."""
        periodic = sorted(
            self.run_dir.glob("step_*.zip"),
            key=lambda p: p.stat().st_mtime,
        )
        if len(periodic) <= self.max_periodic:
            return

        to_remove = periodic[: len(periodic) - self.max_periodic]
        for old in to_remove:
            old.unlink(missing_ok=True)
            meta = old.with_name(old.stem + ".meta.json")
            meta.unlink(missing_ok=True)
            log.info("Cleaned up old periodic checkpoint: %s", old.name)

    # ------------------------------------------------------------------
    # Resume helpers (class methods — no instance needed)
    # ------------------------------------------------------------------

    @staticmethod
    def find_latest_for_run(
        base_dir: Path,
        run_id: str,
    ) -> Path | None:
        """Find the most recent checkpoint from a specific run.

        Matches run directories containing the run_id (e.g. a W&B short ID),
        or metadata files where wandb_run_id matches.
        """
        best: tuple[int, float, Path] | None = None  # (step, timestamp, path)

        for meta_file in base_dir.rglob("*.meta.json"):
            # Check if run_id appears in the parent directory name or metadata
            dir_match = run_id in meta_file.parent.name

            if not dir_match:
                try:
                    meta = json.loads(meta_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                if meta.get("wandb_run_id") != run_id:
                    continue
            else:
                try:
                    meta = json.loads(meta_file.read_text())
                except (json.JSONDecodeError, OSError):
                    continue

            zip_path = meta_file.with_name(
                meta_file.name.replace(".meta.json", ".zip")
            )
            if not zip_path.exists():
                continue

            step = meta.get("step", 0)
            ts = meta_file.stat().st_mtime
            if best is None or (step, ts) > (best[0], best[1]):
                best = (step, ts, zip_path)

        return best[2] if best else None

    @staticmethod
    def find_latest_for_config(
        base_dir: Path,
        config_path: str,
    ) -> Path | None:
        """Find the most recent checkpoint produced by the same config file.

        Scans all run directories for metadata matching the config name,
        then returns the newest checkpoint by step count.
        """
        config_name = Path(config_path).stem
        best: tuple[int, float, Path] | None = None  # (step, timestamp, path)

        for meta_file in base_dir.rglob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            if meta.get("config_name") != config_name:
                continue

            zip_path = meta_file.with_name(
                meta_file.name.replace(".meta.json", ".zip")
            )
            if not zip_path.exists():
                continue

            step = meta.get("step", 0)
            ts = meta_file.stat().st_mtime
            if best is None or (step, ts) > (best[0], best[1]):
                best = (step, ts, zip_path)

        return best[2] if best else None

    @staticmethod
    def find_latest(base_dir: Path) -> Path | None:
        """Find the most recent checkpoint across all runs (any config)."""
        best: tuple[float, Path] | None = None

        for meta_file in base_dir.rglob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            zip_path = meta_file.with_name(
                meta_file.name.replace(".meta.json", ".zip")
            )
            if not zip_path.exists():
                continue

            ts = meta_file.stat().st_mtime
            if best is None or ts > best[0]:
                best = (ts, zip_path)

        return best[1] if best else None

    @staticmethod
    def find_latest_compatible(
        base_dir: Path,
        config_path: str | None,
        validator,
    ) -> Path | None:
        """Find the newest checkpoint that passes validation, scoped to config if given."""
        config_name = Path(config_path).stem if config_path else None

        candidates: list[tuple[float, Path]] = []
        for meta_file in base_dir.rglob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            if config_name and meta.get("config_name") != config_name:
                continue

            zip_path = meta_file.with_name(
                meta_file.name.replace(".meta.json", ".zip")
            )
            if zip_path.exists():
                candidates.append((meta_file.stat().st_mtime, zip_path))

        # Try newest first
        for _, zip_path in sorted(candidates, reverse=True):
            try:
                validator(zip_path)
                return zip_path
            except Exception:
                continue
        return None
