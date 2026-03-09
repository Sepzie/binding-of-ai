#!/bin/bash
# Symlink the mod into Isaac's mod directory.
# Usage: ./install_mod.sh [ISAAC_MOD_DIR]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOD_SRC="$SCRIPT_DIR/../mod"
MOD_NAME="IsaacRL"
ISAAC_MOD_DIR="${1:-}"

find_mod_dir() {
    for dir in \
        "$HOME/snap/steam/common/.local/share/Steam/steamapps/common/The Binding of Isaac Rebirth/mods" \
        "$HOME/.local/share/Steam/steamapps/common/The Binding of Isaac Rebirth/mods" \
        "$HOME/.steam/steam/steamapps/common/The Binding of Isaac Rebirth/mods" \
        "$HOME/snap/steam/common/.local/share/Steam/steamapps/compatdata/250900/pfx/drive_c/users/steamuser/Documents/My Games/Binding of Isaac Repentance/mods" \
        "$HOME/.local/share/Steam/steamapps/compatdata/250900/pfx/drive_c/users/steamuser/Documents/My Games/Binding of Isaac Repentance/mods" \
        "$HOME/snap/steam/common/.local/share/binding of isaac afterbirth+ mods" \
        "$HOME/.local/share/binding of isaac afterbirth+ mods" \
        "$HOME/Library/Application Support/Binding of Isaac Afterbirth+ Mods"; do
        if [ -d "$dir" ] || [ -d "$(dirname "$dir")" ]; then
            printf '%s\n' "$dir"
            return 0
        fi
    done

    return 1
}

if [ -z "$ISAAC_MOD_DIR" ]; then
    ISAAC_MOD_DIR="$(find_mod_dir || true)"
fi

if [ -z "$ISAAC_MOD_DIR" ]; then
    echo "Error: Could not find Isaac mod directory."
    echo "Usage: $0 /path/to/isaac/mods"
    exit 1
fi

mkdir -p "$ISAAC_MOD_DIR"

TARGET="$ISAAC_MOD_DIR/$MOD_NAME"

if [ -L "$TARGET" ]; then
    echo "Removing existing symlink..."
    rm "$TARGET"
elif [ -e "$TARGET" ]; then
    echo "Removing existing path..."
    rm -rf "$TARGET"
fi

ln -s "$MOD_SRC" "$TARGET"
echo "Mod installed: $TARGET -> $MOD_SRC"
