# ArtistLedger Frontend

Static frontend for the ArtistLedger Intelligent Contract, deployed on
GenLayer Studio Network (chain 61999).

- Contract: `0x14b79645F7992c27e2a5Ec61420dD9a82206103c`
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
- **Real wallet connect is the default path.** "Connect" now talks to
  whatever `window.ethereum` is injected (MetaMask first-class): it adds
  studionet (chainId 61999) to the wallet, installs the GenLayer snap
  (`npm:genlayer-wallet-plugin`) so MetaMask understands the chain, and
  signs `register_artist` with your real account via `eth_sendTransaction`
  — the SDK client is created WITHOUT an account so its transport routes
  wallet methods to the provider, and the signer is attached per-call at
  submit (verified in harness: `eth_sendTransaction` from = wallet, to =
  consensus contract, 1162-byte calldata envelope). If the snap install is
  declined, it falls back to a plain EIP-1193 chain-add + sign.
- **Demo key is the fallback only** when no `window.ethereum` exists
  (e.g. embedded/portal contexts — Studio's 1inch pairing is
  WalletConnect QR, which injects no provider). Studionet writes need
  **no gas**, so a zero-balance generated key (kept in localStorage,
  plainly marked "demo key · disposable") still works as a local write
  path for testing. The header's "Reset key" button wipes and rotates it.
- Reads use `readContract({ jsonSafeReturn: true })`; writes go through
  the active signer (local account or injected provider).
- `register_artist` can land `UNDETERMINED` on studionet: validators
  independently re-fetch live APIs and results drift beyond tolerance.
  Re-submission usually lands within a consensus round.
