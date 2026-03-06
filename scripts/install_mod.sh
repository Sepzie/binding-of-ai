#!/bin/bash
# Symlink the mod into Isaac's mod directory
# Usage: ./install_mod.sh [ISAAC_MOD_DIR]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOD_SRC="$SCRIPT_DIR/../mod"

# Default Isaac mod directory (Linux Steam)
ISAAC_MOD_DIR="${1:-$HOME/.local/share/binding of isaac afterbirth+ mods}"

if [ ! -d "$ISAAC_MOD_DIR" ]; then
    # Try alternate locations
    for dir in \
        "$HOME/.local/share/binding of isaac afterbirth+ mods" \
        "$HOME/.steam/steam/steamapps/common/The Binding of Isaac Rebirth/mods" \
        "$HOME/Library/Application Support/Binding of Isaac Afterbirth+ Mods"; do
        if [ -d "$dir" ]; then
            ISAAC_MOD_DIR="$dir"
            break
        fi
    done
fi

if [ ! -d "$ISAAC_MOD_DIR" ]; then
    echo "Error: Could not find Isaac mod directory."
    echo "Usage: $0 /path/to/isaac/mods"
    exit 1
fi

TARGET="$ISAAC_MOD_DIR/IsaacRL"

if [ -L "$TARGET" ]; then
    echo "Removing existing symlink..."
    rm "$TARGET"
elif [ -d "$TARGET" ]; then
    echo "Error: $TARGET already exists and is not a symlink. Remove it manually."
    exit 1
fi

ln -s "$MOD_SRC" "$TARGET"
echo "Mod installed: $TARGET -> $MOD_SRC"
