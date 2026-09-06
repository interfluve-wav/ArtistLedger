#!/bin/bash
# submit_burial_vps.sh — submit register_artist for Burial to studionet,
# bypassing the genlayer CLI's OS-keychain requirement.
#
# Why: the genlayer CLI's `write` command requires the keystore to be
# unlocked via `genlayer account unlock`, which on a headless Linux VPS
# without a real PAM session fails (no `login` keyring collection).
# This script uses the stdlib genlayer-js SDK via Node directly, plus
# eth_account to decrypt the keystore with the password from the
# standard genlayer keychain-pass file.
#
# Pre-conditions:
#   - The contract is deployed at the address in $CONTRACT
#   - /root/.genlayer/keystores/imported-deployer.json exists
#   - /root/.genlayer/keystore-pass-imported contains the password
#   - node, python3, genlayer-js installed
#
# Usage:
#   bash scripts/submit_burial_vps.sh
#
# Result: tx hash printed. Use scripts/watch_receipt.sh to poll.
set -euo pipefail

CONTRACT="${CONTRACT:-0x4Da983553c0aafc16fD1Be26AcE5c0C2308EE760}"
DEPLOYER="0xd3b809526bbd29f699b046e678190a777fd054a9"
KEYSTORE="${KEYSTORE:-/root/.genlayer/keystores/imported-deployer.json}"
PW_FILE="${PW_FILE:-/root/.genlayer/keystore-pass-imported}"
ARTIST_NAME="Burial"
DID="did:musicbrainz:artist:9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"
APPLE_MUSIC_URL="https://music.apple.com/us/artist/burial/468355684?uo=4"
APPLE_MUSIC_ID="468355684"
MB_URL="https://musicbrainz.org/artist/9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"
AUDIO_HASH="11$(printf '11%.0s' {1..31})"  # 64 hex chars, no 0x

VENV=".venv"
PK_FILE="/tmp/.pk-$$"

# Sanity
[ -f "$KEYSTORE" ] || { echo "ERROR: keystore not found at $KEYSTORE"; exit 1; }
[ -f "$PW_FILE" ]   || { echo "ERROR: password file not found at $PW_FILE"; exit 1; }
[ -d "$VENV" ]      || { echo "ERROR: venv not found at $VENV (run python3 -m venv .venv && pip install -e '.[dev]')"; exit 1; }

# Decrypt the keystore
PW=$(cat "$PW_FILE")
trap "rm -f $PK_FILE; shred -u $PK_FILE 2>/dev/null || true" EXIT

$VENV/bin/python - "$PW" "$KEYSTORE" "$PK_FILE" <<'PYEOF'
import json, sys
from eth_account import Account
pw, ks_path, pk_out = sys.argv[1], sys.argv[2], sys.argv[3]
ks = json.load(open(ks_path))
priv = Account.decrypt(ks, pw)
with open(pk_out, 'w') as f:
    f.write(priv.hex())
import os
os.chmod(pk_out, 0o600)
PYEOF

# Build and submit the transaction via genlayer-js
node - "$PK_FILE" "$CONTRACT" "$ARTIST_NAME" "$DID" "$AUDIO_HASH" "$DEPLOYER" "$APPLE_MUSIC_ID" "$MB_URL" <<'JSEOF'
const fs = require('fs');
const sdk = require('/usr/local/lib/node_modules/genlayer/node_modules/genlayer-js');
const [
  , pkFile, contractAddr, name, did, audioHashHex, wallet, appleId, mbUrl
] = process.argv;
const pk = '0x' + fs.readFileSync(pkFile, 'utf8').trim();
const acct = sdk.createAccount(pk);
console.log('submitting from:', acct.address);
const client = sdk.createClient({ chain: sdk.chains.studionet, account: acct });
const args = [
  did, name, '0x' + audioHashHex,
  { apple_music: 'https://music.apple.com/us/artist/burial/' + appleId + '?uo=4',
    musicbrainz: mbUrl },
  wallet,
  'apple_music', appleId,
  'musicbrainz', '9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6',
  true,
];
client.writeContract({
  address: contractAddr,
  functionName: 'register_artist',
  args,
}).then(tx => {
  console.log('TX_HASH=' + tx);
}).catch(e => {
  console.error('FAILED:', e.message);
  if (e.cause) console.error('  cause:', e.cause?.message || JSON.stringify(e.cause));
  process.exit(1);
});
JSEOF

echo "(privkey file wiped)"
