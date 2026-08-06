#!/bin/bash
# Build the Air Picture site and publish it to Cloudflare Pages.
#
# Publishing used to go through git: commit docs/, push, and let a GitHub
# Actions workflow deploy to GitHub Pages. That coupled every site refresh to
# CI capacity, and on 2026-08-06 it stopped working entirely - not because of
# anything here, but because GitHub was failing to allocate runners at all
# ("The job was not acquired by Runner of type hosted"), so jobs queued for up
# to an hour and died without executing a single step.
#
# It was also self-inflicted load: with no paths filter on the lint workflows,
# each data-only push fired four workflows - Pylint, Bandit, CodeQL and Pages -
# roughly 96 times a day, to publish HTML that no linter has any interest in.
#
# Now the generated site is deployed straight to Cloudflare Pages, which takes
# about three seconds and depends on no runner, no OIDC token and no queue.
# docs/ is no longer committed at all, so the lint workflows only run when the
# code actually changes.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO/air_picture.log"
PROJECT="air-picture"

log() { echo "[build_and_push] $*" | tee -a "$LOG"; }

cd "$REPO"

# Bound the log before appending to it. launchd holds this file's descriptor, so
# the trim is in place rather than a rename - see logs.py.
"$REPO/.venv/bin/python" -c "import logs; logs.trim_in_place()" || true

log "Running build_site.py…"
"$REPO/.venv/bin/python" "$REPO/build_site.py"

if [ ! -f "$REPO/docs/index.html" ]; then
    # Deploying an empty or half-built docs/ would replace a good site with a
    # broken one, and Pages has no notion of "this looks wrong, keep the last".
    log "ERROR: docs/index.html missing after build - refusing to deploy."
    exit 1
fi

log "Deploying docs/ to Cloudflare Pages…"
npx --yes wrangler pages deploy "$REPO/docs" \
    --project-name "$PROJECT" --branch main --commit-dirty=true 2>&1 | tee -a "$LOG"

log "Published to https://${PROJECT}.pages.dev"
