import json
from pathlib import Path
from datetime import datetime


def log_reward_components(components: dict, log_file: Path):
    """Append reward component breakdown to a JSONL file for debugging."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        **components,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def find_latest_checkpoint(checkpoint_dir: str) -> str | None:
    """Find the most recent checkpoint in a directory."""
    path = Path(checkpoint_dir)
    if not path.exists():
        return None
    checkpoints = sorted(path.glob("isaac_rl_*.zip"), key=lambda p: p.stat().st_mtime)
    if checkpoints:
        return str(checkpoints[-1])
    return None
