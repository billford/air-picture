#!/bin/bash
# Build the Air Picture site and push to GitHub Pages.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO/air_picture.log"
DATE="$(date -u '+%Y-%m-%d')"

log() { echo "[build_and_push] $*" | tee -a "$LOG"; }

cd "$REPO"

log "Running build_site.py…"
"$REPO/.venv/bin/python" "$REPO/build_site.py"

# Stage only the generated docs/ output
git add docs/

if git diff --cached --quiet; then
    log "No changes to commit."
    exit 0
fi

git commit -m "site: air picture $DATE"
log "Committed."

git push
log "Pushed to origin."
