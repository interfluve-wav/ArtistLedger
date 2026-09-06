#!/bin/bash
# faucet_watch.sh — poll a list of addresses for non-zero GEN balance.
#
# Usage:
#   bash scripts/faucet_watch.sh 0xADDR1 0xADDR2 ...
#   bash scripts/faucet_watch.sh 0xADDR1 --once    # one check, exit
#
# Polls every 30s. Exits 0 the first time ANY address shows non-zero balance.
# Exits 1 on SIGINT. Logs all results to /tmp/faucet_watch.log.
set -u
LOG=/tmp/faucet_watch.log
INTERVAL=30
ONCE=0
ADDRS=()
for a in "$@"; do
  if [ "$a" = "--once" ]; then ONCE=1
  else ADDRS+=("$a")
  fi
done
if [ ${#ADDRS[@]} -eq 0 ]; then
  echo "Usage: $0 0xADDR1 [0xADDR2 ...] [--once]" >&2
  exit 2
fi
RPC="https://studio.genlayer.com/api"
poll() {
  local addr="$1"
  curl -sS -X POST -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getBalance\",\"params\":[\"$addr\",\"latest\"],\"id\":1}" \
    "$RPC" | python3 -c "
import json, sys
try:
    r = json.load(sys.stdin)['result']
    print(int(r, 16))
except Exception:
    print(0)
"
}
echo "[$(date -u +%FT%TZ)] watching ${#ADDRS[@]} address(es) on $RPC" | tee -a "$LOG"
trap 'echo "[$(date -u +%FT%TZ)] interrupted" | tee -a "$LOG"; exit 1' INT TERM
while true; do
  for a in "${ADDRS[@]}"; do
    bal=$(poll "$a")
    if [ "$bal" -gt 0 ]; then
      msg="FUNDED: $a has $bal wei ($(echo "scale=6; $bal / 10^18" | bc) GEN)"
      echo "[$(date -u +%FT%TZ)] $msg" | tee -a "$LOG"
      echo "$msg"
      exit 0
    fi
    echo "[$(date -u +%FT%TZ)] $a = $bal wei (0)" >> "$LOG"
  done
  if [ "$ONCE" -eq 1 ]; then exit 0; fi
  sleep "$INTERVAL"
done
