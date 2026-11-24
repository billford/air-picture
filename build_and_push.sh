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
set -Eeuo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO/air_picture.log"
PROJECT="air-picture"

# launchd starts jobs with PATH=/usr/bin:/bin:/usr/sbin:/sbin - it does not read
# the login shell's profile, so Homebrew's bin is absent and npx is simply not
# there. That is how this script ran fine by hand and died with exit 127 on
# every scheduled run for a full day after the move to Pages.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

log() { echo "[build_and_push] $*" | tee -a "$LOG"; }

# Push a pipeline alert. Never allowed to fail the deploy: a broken notifier
# must not become a broken publish.
alert() { "$REPO/.venv/bin/python" -m alerts "$1" "site deploy" "$2" >>"$LOG" 2>&1 || true; }

# One EXIT trap rather than ERR, so it also catches the explicit `exit 1`
# guards below - those do not fire ERR. Any non-zero exit notifies once, then
# stays quiet until it recovers or ALERT_REPEAT_HOURS passes; see alerts.py.
#
# This exists because the npx/PATH breakage below failed 105 times in a day and
# said so only in a logfile nobody had reason to open.
on_exit() {
    local code=$?
    [ "$code" -eq 0 ] && return 0
    alert failure "$(printf 'Exit %s.\n\nLast log lines:\n%s' "$code" "$(tail -n 12 "$LOG")")"
}
trap on_exit EXIT

cd "$REPO"

# wrangler auth. On lola, a token scoped to Pages for this one project lives in
# .env; nobody is at lola's screen to run `wrangler login`, and sharing the
# laptop's OAuth login would break whichever machine refreshed it second.
# Where neither is set, wrangler falls back to its own login, as before. Only
# these two keys are read: sourcing .env would export every secret in it into
# npx's environment.
for key in CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID; do
    val="$(grep -E "^${key}=" "$REPO/.env" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d "\"'")" || true
    if [ -n "$val" ]; then export "$key=$val"; fi
done

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

if ! command -v npx >/dev/null 2>&1; then
    # Say which tool is missing and where we looked, rather than leaving a bare
    # "npx: command not found" from inside the pipeline below.
    log "ERROR: npx not found on PATH ($PATH) - cannot deploy. Is node installed?"
    exit 1
fi

log "Deploying docs/ to Cloudflare Pages…"
npx --yes wrangler pages deploy "$REPO/docs" \
    --project-name "$PROJECT" --branch main --commit-dirty=true 2>&1 | tee -a "$LOG"

log "Published to https://${PROJECT}.pages.dev"

# Only says anything if the previous run was failing, so the ~96 healthy runs a
# day stay silent.
alert recovery "Site is publishing again: https://${PROJECT}.pages.dev"
