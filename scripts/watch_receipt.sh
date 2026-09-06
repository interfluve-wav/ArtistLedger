#!/bin/bash
# watch_receipt.sh — poll for transaction finalization on studionet.
# Usage: bash scripts/watch_receipt.sh <tx_hash> [max_minutes]
set -euo pipefail

TX="${1:?usage: watch_receipt.sh <tx_hash> [max_minutes]}"
MAX_MIN="${2:-30}"
INTERVAL=15
ITER=$((MAX_MIN * 60 / INTERVAL))

echo "Watching $TX for up to ${MAX_MIN} min (every ${INTERVAL}s)..."
for i in $(seq 1 $ITER); do
  out=$(curl -sS -X POST -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getTransactionReceipt\",\"params\":[\"$TX\"],\"id\":1}" \
    https://studio.genlayer.com/api)
  bn=$(echo "$out" | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r.get('blockNumber','0x0'))" 2>/dev/null)
  if [ "$bn" != "0x0" ] && [ "$bn" != "?" ]; then
    echo "✓ FINALIZED at iter $i, block=$bn"
    echo "$out" | python3 -m json.tool
    exit 0
  fi
  if [ $((i % 4)) -eq 0 ]; then
    echo "  (iter $i / $ITER, still pending)"
  fi
  sleep $INTERVAL
done
echo "✗ timeout after ${MAX_MIN} min"
exit 1
