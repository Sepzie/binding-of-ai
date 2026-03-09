#!/bin/bash
# Launch training pipeline
# Usage: ./launch_training.sh [config_file] [--resume checkpoint_path|latest|latest-compatible]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="$SCRIPT_DIR/../python"

CONFIG="${1:-$SCRIPT_DIR/../configs/phase1a.yaml}"
shift 2>/dev/null || true

cd "$PYTHON_DIR"

# Use venv if available
VENV="$SCRIPT_DIR/../.venv/bin/python"
if [ -x "$VENV" ]; then
    PYTHON="$VENV"
else
    PYTHON="python3"
fi

"$PYTHON" train.py --config "$CONFIG" "$@"
