#!/bin/bash
# Install air-picture's five launchd jobs for this checkout and this account.
#
# The plists here name the repo as __REPO__; this fills in the real path, so
# the same files serve any machine and account (the laptop until 2026-11,
# lola since). Re-running replaces jobs already loaded.
#
#   launchd/install.sh            install and load
#   launchd/install.sh --remove   unload and delete
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
mkdir -p "$DEST"

for src in "$REPO"/launchd/local.air-picture.*.plist; do
    name="$(basename "$src" .plist)"
    launchctl bootout "$DOMAIN/$name" 2>/dev/null || true
    if [ "${1:-}" = "--remove" ]; then
        rm -f "$DEST/$name.plist"
        echo "removed $name"
        continue
    fi
    sed "s#__REPO__#$REPO#g" "$src" > "$DEST/$name.plist"
    plutil -lint -s "$DEST/$name.plist"
    launchctl bootstrap "$DOMAIN" "$DEST/$name.plist"
    echo "loaded $name"
done
