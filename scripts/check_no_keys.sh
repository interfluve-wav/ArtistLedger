#!/bin/bash
# check_no_keys.sh — refuse git push/deploy if any private key material lands in the tree.
# Wired into: .git/hooks/pre-push, scripts/autodeploy.sh (deploy guard), and CI.
# False positives are cheap; a leaked key is not. But it must not flag
# legitimate infra: CA bundles (*.pem with public certs) and gitignored
# local .env files are allowed to EXIST on disk — they may never be TRACKED.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1

fail=0

# helper: emit only paths that are NOT pruned dirs
prune() {
  find . \( -path ./.git -o -path ./node_modules -o -path ./.venv \) -prune -o "$@"
}

file_contains_private_key() {
  # real secret material = ASN.1/PEM private-key headers or keystore ciphertext
  grep -qE -- '-----BEGIN (RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----' "$1" 2>/dev/null || \
  grep -q '"ciphertext"' "$1" 2>/dev/null
}

# 1. Any file (tracked OR untracked) whose CONTENTS are a private key / keystore
hits=$(prune -type f -print 2>/dev/null | while read -r f; do
  case "$f" in
    *.pem|*.key|*.keystore|*UTC--*.json|*.p12|*.pfx) file_contains_private_key "$f" && echo "$f" ;;
  esac
done | head -20)
if [ -n "$hits" ]; then
  echo "BLOCKED: private-key CONTENTS detected:"
  echo "$hits"; fail=1
fi

# 2. Named key/keystore files (regardless of content) — presence in tree = block
hits=$(prune -type f \( -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'keys.enc' \
  -o -name 'wallet*.json' -o -name 'accounts*.json' -o -name 'wallets*.json' \
  -o -name '*keystore-pass*' -o -name '*_clean_pw' -o -name 'UTC--*.json' \
  -o -name '*.keystore' \) -print 2>/dev/null | head -20)
if [ -n "$hits" ]; then
  echo "BLOCKED: key-named files in tree:"
  echo "$hits"; fail=1
fi

# 3. Secrets must never be TRACKED by git (on-disk local copies are fine)
if git rev-parse --git-dir >/dev/null 2>&1; then
  hits=$(git ls-files | grep -E '(^|/)(\.env.*)$|(^|/)keystore|\.genlayer|(^|/)wallet|(^|/)private|(^|/)secret|(^|/)_pw' | grep -v '^frontend/lib/' | head -20)
  if [ -n "$hits" ]; then
    echo "BLOCKED: secret files TRACKED by git:"
    echo "$hits"; fail=1
  fi

  # 4. Staged diff must not introduce key material
  hits=$(git diff --cached --name-only --diff-filter=ACM | while read -r f; do
    [ -f "$f" ] && file_contains_private_key "$f" && echo "$f"
  done | head -20)
  if [ -n "$hits" ]; then
    echo "BLOCKED: staged files containing private-key material:"
    echo "$hits"; fail=1
  fi
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "Aborting: private key material detected. Keys belong in ~/.genlayer/, never the repo."
  exit 1
fi
echo "check_no_keys: clean"
exit 0