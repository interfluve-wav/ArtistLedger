#!/bin/bash
# Run Burial register_artist test on studionet
# Pre-conditions:
#   - imported-deployer (or other account) has >= 1 GEN
#   - studionet faucet unpaused
#   - network = studionet (genlayer network set studionet)
set -euo pipefail
cd "$(dirname "$0")/.."

DID='did:musicbrainz:artist:9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6'
NAME='Burial'
AUDIO='b#1111111111111111111111111111111111111111111111111111111111111111'
SRC='{"apple_music":"https://music.apple.com/us/artist/burial/468355684?uo=4","musicbrainz":"https://musicbrainz.org/artist/9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"}'
WALLET='0xd3b809526bbd29f699b046e678190a777fd054a9'
VS1='apple_music'
VH1='468355684'
VS2='musicbrainz'
VH2='9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6'
STRICT='true'

genlayer write 0x4Da983553c0aafc16fD1Be26AcE5c0C2308EE760 register_artist \
  --args "$DID" "$NAME" "$AUDIO" "$SRC" "$WALLET" "$VS1" "$VH1" "$VS2" "$VH2" "$STRICT"
