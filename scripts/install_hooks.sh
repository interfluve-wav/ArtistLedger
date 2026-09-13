#!/bin/bash
# install_hooks.sh — wire secret-scan into every push + deploy.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$REPO/.git/hooks"
cp "$REPO/.githooks/pre-push" "$REPO/.git/hooks/pre-push"
chmod +x "$REPO/.git/hooks/pre-push" "$REPO/scripts/check_no_keys.sh"
echo "Installed: .git/hooks/pre-push -> scripts/check_no_keys.sh"
"$REPO/scripts/check_no_keys.sh" && echo "pre-push guard active (clean tree)"