# QUICKSTART — run, test, verify

Everything you need to run ArtistLedger locally and verify it on-chain.
No paid APIs. No keys. No build step.

## 1. Contract tests (the whole gate)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pytest -q                 # 174 passed
bash scripts/ci_local.sh  # same gate CI runs
```

`scripts/ci_local.sh` = pytest + static checks + `scripts/check_no_keys.sh`
(blocks commits that would leak wallet keys or credentials).

## 2. Frontend (local)

The frontend is static HTML/JS — no bundler. It talks to the GenLayer
RPC directly from the browser.

```bash
cd frontend
python3 -m http.server 8000
# open http://localhost:8000
```

Tap **Disposable Testnet Key** to get a demo wallet (generated locally,
persisted in your browser only), then any artist chip → **Sign & submit
proof** → certificate.

## 3. Live demo + deployed contract

- Demo: https://artistledger-frontend.vercel.app
- Contract: `0xB110dA64B1c14B65c078430fd6Bd0f9E79d83981`
  (studionet, chainId 61999)
- Explorer: https://explorer-studio.genlayer.com/address/0xB110dA64B1c14B65c078430fd6Bd0f9E79d83981

Verify the chain is reachable:

```bash
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  https://studio.genlayer.com/api
# → {"jsonrpc":"2.0","result":"0x...","id":1}  (live block height)
```

The frontend header shows `connected · 15 methods · contract
0xB110dA64…3981 · v0.7.2` when the RPC is up.

## 4. Deploy the frontend (Vercel)

```bash
# from the repo ROOT (Vercel root dir is frontend/)
npx vercel deploy --prod --yes
```

## 5. How the verification works (30 seconds)

1. Leader collects evidence from 8 free public APIs + an LLM
   press-narrative judge.
2. Validators deterministically re-derive the score from the same
   evidence — no live re-fetch, so consensus can't drift on rate
   limits.
3. Majority agreement → the certificate flips to **VRFD** (lenient
   ≥ 60) with an honest dual score (strict on-chain + lenient
   projection).
4. **Inspect** shows the raw evidence JSON, the exact `register_artist`
   calldata, and the validator consensus (`MAJORITY_AGREE`,
   `FINALIZED`).

## Troubleshooting

- **Connect popup doesn't appear** — you visited before; clear site
  data for the domain or open in a private window.
- **Consensus takes 30-60s** — normal; 4 validators re-derive the
  score on-chain.
- **Strict score low (20-31)** — by design: without an AcoustID
  fingerprint in `audio_hash` the strict rubric caps at tier-1
  sources; the lenient projection overlays this honestly.
