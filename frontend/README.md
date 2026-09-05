# ArtistLedger Frontend

Static frontend for the ArtistLedger Intelligent Contract, deployed on
GenLayer Studio Network (chain 61999).

- Contract: `0x4Da983553c0aafc16fD1Be26AcE5c0C2308EE760`
- RPC: `https://studio.genlayer.com/api` (CORS open)

## Run locally

```bash
python3 -m http.server 8791
# open http://localhost:8791
```

No build step: `lib/genlayer-sdk.js` is a pre-bundled `genlayer-js@1.1.8`
(esbuild IIFE) exposing `window.GenLayerSDK`. To rebuild:

```bash
npm i genlayer-js@1.1.8 esbuild
echo 'import * as GL from "genlayer-js"; window.GenLayerSDK = GL;' > entry.js
npx esbuild entry.js --bundle --format=iife --platform=browser \
    --target=es2020 --minify --outfile=frontend/lib/genlayer-sdk.js
```

## Quirks (verified 2026-09-05 against live Studio RPC)

- `gen_getContractSchema` requires a **plain string** param (contract
  address), not `{address: ...}` — the SDK's `getContractSchema()` sends a
  dict and gets a psycopg2 error. `app.js` boot() does the raw request with
  a fallback.
- Reads use `readContract({ jsonSafeReturn: true })`; writes go through the
  injected `window.ethereum` provider (e.g. 1inch wallet) with
  `wallet_switchEthereumChain` to `0xf22f` (61999) on connect.
- `register_artist` can land `UNDETERMINED` on studionet: validators
  independently re-fetch live APIs and results drift beyond tolerance.
