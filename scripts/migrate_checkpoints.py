"""Migrate legacy flat checkpoints into the new per-run folder structure.

Scans checkpoints/*.zip (flat files without metadata) and moves them into
a legacy run folder with best-effort metadata extracted from filenames.

Usage:
    python scripts/migrate_checkpoints.py [--dry-run]
"""

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = REPO_ROOT / "checkpoints"

# Match existing checkpoint filenames like:
#   20260309_112443_isaac_rl_50000_steps.zip
#   20260309_171233_final_model.zip
#   20260310_003336_crashed_model.zip
#   model.zip
TIMESTAMP_RE = re.compile(r"^(\d{8}_\d{6})_(.+)\.zip$")
STEP_RE = re.compile(r"isaac_rl_(\d+)_steps")


def extract_metadata(zip_path: Path) -> dict:
    """Extract best-effort metadata from a legacy checkpoint filename."""
    name = zip_path.stem
    meta = {
        "run_id": "legacy",
        "config_path": None,
        "config_name": "unknown",
        "git_commit": None,
        "timestamp": datetime.fromtimestamp(zip_path.stat().st_mtime).isoformat(),
        "step": 0,
        "reason": "unknown",
        "wandb_run_id": None,
        "wandb_project": None,
        "migrated_from": zip_path.name,
    }

    # Extract timestamp from filename
    ts_match = TIMESTAMP_RE.match(zip_path.name)
    if ts_match:
        ts_str = ts_match.group(1)
        try:
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            meta["timestamp"] = dt.isoformat()
        except ValueError:
            pass
        name = ts_match.group(2)

    # Extract step count
    step_match = STEP_RE.search(name)
    if step_match:
        meta["step"] = int(step_match.group(1))
        meta["reason"] = "periodic"

    # Extract reason from name
    if "final_model" in name:
        meta["reason"] = "final"
    elif "interrupted_model" in name:
        meta["reason"] = "interrupted"
    elif "crashed_model" in name:
        meta["reason"] = "crashed"

    return meta


def migrate(dry_run: bool = False):
    """Move flat checkpoint zips into a legacy/ subfolder with metadata."""
    flat_zips = [
        f for f in CHECKPOINT_DIR.iterdir()
        if f.is_file() and f.suffix == ".zip"
    ]

    if not flat_zips:
        print("No flat checkpoints to migrate.")
        return

    print(f"Found {len(flat_zips)} flat checkpoint(s) to migrate.")

    legacy_dir = CHECKPOINT_DIR / "legacy"
    if not dry_run:
        legacy_dir.mkdir(exist_ok=True)

    for zip_path in sorted(flat_zips):
        meta = extract_metadata(zip_path)
        dest = legacy_dir / zip_path.name
        meta_dest = legacy_dir / f"{zip_path.stem}.meta.json"

        if dry_run:
            print(f"  [dry-run] {zip_path.name} -> legacy/{zip_path.name}")
            print(f"            reason={meta['reason']}, step={meta['step']}")
        else:
            shutil.move(str(zip_path), str(dest))
            meta_dest.write_text(json.dumps(meta, indent=2))
            print(f"  Migrated {zip_path.name} (reason={meta['reason']}, step={meta['step']})")

    print(f"\nDone. {'Would migrate' if dry_run else 'Migrated'} {len(flat_zips)} checkpoint(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate flat checkpoints to per-run structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without moving files")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
