#!/bin/bash
# Local CI parity: run the exact gates .github/workflows/ci.yml runs.
# Usage: bash scripts/ci_local.sh   (exit 0 = all green, safe to push)
set -u
cd "$(dirname "$0")/.." || exit 1
FAIL=0
step() { echo "=== $1 ==="; }

step "1/4 pytest (contract + validator tests)"
# venv python (system python3 has no pytest outside an activated venv)
PYBIN="$(dirname "$0")/../.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN=python3
"$PYBIN" -m pytest tests/ -q || FAIL=1

step "2/4 frontend JS syntax"
JSFAIL=0
for f in $(find frontend -name '*.js' -not -path 'frontend/lib/*'); do
  node --check "$f" || { echo "SYNTAX FAIL: $f"; JSFAIL=1; }
done
if [ "$JSFAIL" -eq 0 ]; then echo "all frontend JS parse OK"; else FAIL=1; fi

step "3/4 contract pointer"
if grep -q "0xB110dA64B1c14B65c078430fd6Bd0f9E79d83981" frontend/app.js; then
  echo "points at v0.7.2 reverify contract"
else
  echo "FAIL: frontend/app.js does not reference deployed contract"
  FAIL=1
fi

step "4/4 key-material scan"
bash scripts/check_no_keys.sh || FAIL=1

echo
if [ "$FAIL" -eq 0 ]; then
  echo "ALL GATES GREEN"
else
  echo "GATES FAILED - do not push"
fi
exit $FAIL
