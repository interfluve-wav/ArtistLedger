#!/bin/bash
# ArtistLedger auto-deploy watcher: if origin/main moved past the last deployed SHA, deploy to Vercel prod.
set -u
REPO=/root/projects/ArtistLedger
LOG=/var/log/artistledger-autodeploy.log
DEPLOYED_FILE=/root/projects/ArtistLedger/.last-deployed-sha

cd "$REPO" || exit 1
git fetch origin main --quiet 2>>"$LOG" || exit 1
REMOTE=$(git rev-parse origin/main)
LAST=$(cat "$DEPLOYED_FILE" 2>/dev/null || echo "")

if [ "$REMOTE" = "$LAST" ]; then
  exit 0
fi

echo "[$(date -u '+%F %T')] new commit $REMOTE (was ${LAST:-none}), deploying..." >> "$LOG"
OUT=$(vercel deploy --prod 2>&1 | tail -20)
if echo "$OUT" | grep -q "Aliased"; then
  echo "$REMOTE" > "$DEPLOYED_FILE"
  echo "[$(date -u '+%F %T')] deployed OK: $(echo "$OUT" | grep -oE 'https://artistledger-frontend-[a-z0-9-]+\.vercel\.app' | head -1)" >> "$LOG"
else
  echo "[$(date -u '+%F %T')] DEPLOY FAILED: $(echo "$OUT" | tr '\n' ' ' | tail -c 300)" >> "$LOG"
fi
