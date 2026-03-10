import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


CHECKPOINT_FILENAME_RE = re.compile(
    r"^(?:\d{8}_\d{6}_)?"
    r"(?:isaac_rl_\d+_steps|interrupted_model|final_model|crashed_model)"
    r"\.zip$"
)


def log_reward_components(components: dict, log_file: Path):
    """Append reward component breakdown to a JSONL file for debugging."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        **components,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_repo_root() -> Path:
    """Return the repository root regardless of the current working directory."""
    return Path(__file__).resolve().parent.parent


def get_checkpoint_dir() -> Path:
    """Return the repository-local checkpoint directory."""
    return get_repo_root() / "checkpoints"


def get_log_dir() -> Path:
    """Return the repository-local log directory."""
    return get_repo_root() / "logs"


def checkpoint_timestamp() -> str:
    """Return a filesystem-friendly local timestamp prefix."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def timestamped_checkpoint_stem(name: str) -> str:
    """Prefix a checkpoint stem with a sortable timestamp."""
    return f"{checkpoint_timestamp()}_{name}"


def list_checkpoints(checkpoint_dir: str | Path) -> list[Path]:
    """List known checkpoint files sorted by modification time."""
    path = Path(checkpoint_dir)
    if not path.exists():
        return []

    checkpoints = [
        checkpoint for checkpoint in path.glob("*.zip")
        if CHECKPOINT_FILENAME_RE.match(checkpoint.name)
    ]
    return sorted(checkpoints, key=lambda checkpoint: checkpoint.stat().st_mtime)


def find_latest_checkpoint(checkpoint_dir: str) -> str | None:
    """Find the most recent checkpoint in a directory."""
    checkpoints = list_checkpoints(checkpoint_dir)
    if checkpoints:
        return str(checkpoints[-1])
    return None


def find_latest_compatible_checkpoint(
    checkpoint_dir: str | Path,
    validator: Callable[[Path], None] | None = None,
) -> str | None:
    """Find the newest checkpoint that passes validation."""
    for checkpoint in reversed(list_checkpoints(checkpoint_dir)):
        try:
            if validator is not None:
                validator(checkpoint)
            return str(checkpoint)
        except Exception:
            continue
    return None


def validate_ppo_checkpoint(checkpoint_path: Path, env) -> None:
    """Raise if a checkpoint cannot be loaded for the provided environment."""
    try:
        from sb3_contrib import MaskablePPO as PPO
    except ImportError as exc:
        raise ImportError(
            "sb3-contrib is required to validate checkpoints for training."
        ) from exc

    PPO.load(str(checkpoint_path), env=env)
