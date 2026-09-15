#!/bin/bash
# ArtistLedger auto-deploy watcher v2.
# Fixes over v1:
#   1. Never touches the working tree: deploys from a temp git worktree
#      checked out at origin/main, so a feature branch checked out on the
#      VPS can't be reset away by the cron (v1 did `git reset --hard`).
#   2. Runs the CI gates (ci_local.sh) on the deploy tree before shipping —
#      failing tests/syntax/key-scan blocks the deploy.
#   3. Post-deploy smoke: prod URL must return 200 and reference app.js.
#   4. flock guard: overlapping cron runs are no-ops.
set -u
REPO=/root/projects/ArtistLedger
LOG=/var/log/artistledger-autodeploy.log
DEPLOYED_FILE=/root/projects/ArtistLedger/.last-deployed-sha
PROD_URL="https://artistledger-frontend.vercel.app"

exec 9>/tmp/al-autodeploy.lock
flock -n 9 || exit 0

cd "$REPO" || exit 1
git fetch origin main --quiet 2>>"$LOG" || exit 1
REMOTE=$(git rev-parse origin/main)
LAST=$(cat "$DEPLOYED_FILE" 2>/dev/null || echo "")

if [ "$REMOTE" = "$LAST" ]; then
  exit 0
fi

echo "[$(date -u '+%F %T')] new commit $REMOTE (was ${LAST:-none}) — gating + deploying via temp worktree" >> "$LOG"

# --- Prepare isolated deploy tree at origin/main -------------------------
WT=/tmp/al-deploy-wt
git worktree remove --force "$WT" 2>>"$LOG" || true
rm -rf "$WT"
git worktree prune >>"$LOG" 2>&1
git worktree add --detach "$WT" "$REMOTE" --quiet 2>>"$LOG" || {
  echo "[$(date -u '+%F %T')] DEPLOY FAILED: could not create worktree at $WT" >> "$LOG"
  exit 1
}
# vercel needs the project link (.vercel/ is gitignored — copy it in)
cp -r "$REPO/.vercel" "$WT/.vercel"

cleanup() { git worktree remove --force "$WT" 2>>"$LOG" || rm -rf "$WT"; }

# --- Gate 1: CI gates on the deploy tree ---------------------------------
# Inlined (not ci_local.sh) so the gate works even if the CI commit itself
# hasn't landed on origin/main yet.
GATE=0
echo "=== autodeploy gates on $REMOTE ===" >>"$LOG"

cd "$WT" || exit 1
# venv python (pytest lives there; system python3 has no pytest)
PYBIN="$REPO/.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN=python3
"$PYBIN" -m pytest tests/ -q >>"$LOG" 2>&1 || GATE=1

JSFAIL=0
for f in $(find frontend -name '*.js' -not -path 'frontend/lib/*'); do
  node --check "$f" 2>>"$LOG" || JSFAIL=1
done
[ "$JSFAIL" -ne 0 ] && GATE=1

grep -q "0x53867F241e0aa5CF7AD5728F0dA1E063CA811bE8" frontend/app.js 2>>"$LOG" || GATE=1

bash "$WT/scripts/check_no_keys.sh" >>"$LOG" 2>&1 || GATE=1

if [ "$GATE" -ne 0 ]; then
  echo "[$(date -u '+%F %T')] DEPLOY BLOCKED: gates failed on $REMOTE (see gates log above)" >> "$LOG"
  cleanup
  exit 1
fi

# --- Deploy from the worktree --------------------------------------------
OUT=$(cd "$WT" && vercel deploy --prod --yes 2>&1)
DEPLOY_URL=$(echo "$OUT" | grep -oE 'https://artistledger-frontend-[a-z0-9-]+\.vercel\.app' | head -1)
if echo "$OUT" | grep -qE '"status":\s*"ok"|Aliased|Production'; then
  echo "$REMOTE" > "$DEPLOYED_FILE"
  echo "[$(date -u '+%F %T')] deployed OK: $DEPLOY_URL" >> "$LOG"
else
  echo "[$(date -u '+%F %T')] DEPLOY FAILED: $(echo "$OUT" | tr '\n' ' ' | tail -c 300)" >> "$LOG"
  cleanup
  exit 1
fi

# --- Gate 2: post-deploy smoke -------------------------------------------
sleep 3
SMOKE=$(curl -s -o /dev/null -w "%{http_code}" "$PROD_URL")
BODY=$(curl -s "$PROD_URL" | grep -c "app.js" || true)
if [ "$SMOKE" = "200" ] && [ "${BODY:-0}" -ge 1 ]; then
  echo "[$(date -u '+%F %T')] smoke OK: $PROD_URL 200, app.js referenced ($BODY refs)" >> "$LOG"
else
  echo "[$(date -u '+%F %T')] SMOKE FAILED: http=$SMOKE appjs_refs=${BODY:-0}" >> "$LOG"
fi

cleanup
