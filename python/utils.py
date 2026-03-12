from datetime import datetime
from pathlib import Path


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
