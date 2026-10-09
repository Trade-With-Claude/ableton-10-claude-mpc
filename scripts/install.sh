#!/usr/bin/env bash
# Install the ClaudeMPC Remote Script into Ableton's User Library.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/remote_script/ClaudeMPC/"
DEST="${CLAUDE_MPC_DEST:-$HOME/Music/Ableton/User Library/Remote Scripts/ClaudeMPC/}"

mkdir -p "$DEST"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$SRC" "$DEST"
# Live caches compiled scripts: remove stale bytecode so edits are picked up
find "$DEST" -name '*.pyc' -delete

echo "Installed ClaudeMPC -> $DEST"
echo "Next: restart Live (or re-select the surface), then Preferences > Link/MIDI >"
echo "      Control Surface (free slot 2-6) = ClaudeMPC, Input/Output = None."
