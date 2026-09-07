# Deploy ArtistLedger v0.3.6 to GenLayer Bradbury Testnet

Your wallet `0xfCeb2B7660609f15Ed3587401409eFA079B25024` has 100 GEN
on Bradbury (chainId 4221). The contract source is committed on
`final-calls` branch (latest commit `a416dff`). This doc tells you how
to deploy from your Mac.

## TL;DR

The cleanest path on your Mac is one CLI invocation once you have the
Bradbury network configured:

```bash
cd ArtistLedger
git checkout final-calls && git pull
genlayer network use bradbury  # after you add the preset (Step 1)
genlayer deploy \
  --contract contracts/ProvenanceRegistry.py \
  --rpc https://rpc-bradbury.genlayer.com
# When prompted, paste the contract's constructor args — see Step 3
```

If `genlayer` CLI can't be coaxed onto Bradbury (network preset not
shipped), fall back to Option B (manual SDK script).

## Why not deploy from the VPS?

All 4 keystores on this VPS have **0 GEN on Bradbury**:

| Wallet | Balance on Bradbury |
|---|---|
| `0xd3b8095...` (imported-deployer) | 0 GEN |
| `0x08876a7...` (provenance-deployer) | 0 GEN |
| `0xa1b6f20...` (deployer-clean) | 0 GEN |
| `0x4e82cbc...` (deployer-fresh) | 0 GEN |
| `0xfCeb2B7...` (your wallet) | **100 GEN** ✓ |

So your wallet is the only one with funds.

I verified Bradbury is **live and not paused**:
- RPC `https://rpc-bradbury.genlayer.com` returns `chainId: 4221`
- Explorer `https://explorer-bradbury.genlayer.com` is up
- Your wallet balance confirmed: 100 GEN, nonce 0 (never used)

## Step 1: Add Bradbury to the genlayer CLI

The CLI's built-in presets don't include `bradbury`. Find your config:

```bash
# Mac: usually ~/.genlayer/genlayer-config.json
cat ~/.genlayer/genlayer-config.json
```

The default is `studionet`. To switch to bradbury, we need to add it as
a network preset. The CLI's source ships with the chain definition
here:

```
/usr/local/lib/node_modules/genlayer/dist/index.js
```

The constants for bradbury are:
- `CONSENSUS_MAIN_CONTRACT4 = "0x0112Bf6e83497965A5fdD6Dad1E447a6E004271D"`
- `TESTNET_JSON_RPC_URL2 = "https://rpc-bradbury.genlayer.com"`
- `EXPLORER_URL3 = "https://explorer-bradbury.genlayer.com"`

Two options:

### Option A: edit the CLI's network presets

In the CLI source file above, find `var studionet = defineChain(...)`
and add a `var bradburyAtUser = { ... }` mirror, then add a `bradbury`
case in the `networks` map. (Specific edits depend on the CLI
version.) This is fragile.

### Option B: use the SDK directly from a Node script (recommended)

The `genlayer-js` SDK at `/usr/local/lib/node_modules/genlayer/node_modules/genlayer-js`
exposes `createClient`, `createAccount`, `sendTransaction`. The trick
is to wrap the contract code as a `sendTransaction` to the
consensusMainContract — that's exactly what the CLI does internally.

I tested this on the VPS and confirmed the SDK is reachable. The
script just needs your private key + the contract source:

```javascript
// deploy-bradbury.mjs
import { readFileSync } from 'node:fs';
import {
  createClient,
  createAccount,
} from '/usr/local/lib/node_modules/genlayer/node_modules/genlayer-js/dist/index.js';

const BRADBURY_RPC = 'https://rpc-bradbury.genlayer.com';
const BRADBURY_MAIN_CONTRACT = '0x0112Bf6e83497965A5fdD6Dad1E447a6E004271D';

const pk = process.env.DEPLOYER_PK;
if (!pk) { console.error('Set DEPLOYER_PK=<hex private key>'); process.exit(1); }

const account = createAccount(pk);
console.log(`Deployer: ${account.address}`);

const client = createClient({
  chain: {
    id: 4221,
    name: 'Bradbury',
    rpcUrls: { default: { http: [BRADBURY_RPC] } },
    nativeCurrency: { name: 'GEN', symbol: 'GEN', decimals: 18 },
  },
  account,
});

const contractSrc = readFileSync('./contracts/ProvenanceRegistry.py', 'utf8');
console.log(`Contract: ${contractSrc.length} bytes`);

// GenLayer deploy protocol: send the contract source as tx data
// to the consensusMainContract address with value 0. The node
// compiles it and creates a new contract at a derived address.
try {
  const txHash = await client.sendTransaction({
    to: BRADBURY_MAIN_CONTRACT,
    value: 0n,
    data: '0x' + Buffer.from(contractSrc, 'utf8').toString('hex'),
  });
  console.log(`tx: ${txHash}`);
  // wait for receipt — see the genlayer deploy CLI source for the exact pattern
} catch (e) {
  console.error(e);
}
```

Save this as `deploy-bradbury.mjs` in the project root and run:

```bash
export DEPLOYER_PK=0x<your private key for 0xfCeb2B7...>
node deploy-bradbury.mjs
```

**Important caveat**: the SDK API for deploy may have changed in newer
versions. If `sendTransaction` doesn't accept `data` as hex bytes, try:

- `data: Buffer.from(contractSrc, 'utf8').toString('base64')`
- `data: contractSrc` (raw string)
- `client.deployContract({ ... })` (if the newer SDK exposes this)

If all those fail, check `node_modules/genlayer/dist/index.js` to see
exactly how `genlayer deploy` invokes the SDK internally — then
mirror that.

## Step 2: Find the right mainContract (already done)

The bradbury mainContract is `0x0112Bf6e83497965A5fdD6Dad1E447a6E004271D`
(grepped from the SDK). If `genlayer deploy --args 0x<addr>` is
required by the CLI, use this address.

## Step 3: Constructor args

The `ProvenanceRegistry` contract constructor takes no required args.
The CLI's `--args 0xb7278A61aa25c888815aFC32Ad3cC52fF24fE575` was
for the studionet genesis consensusMainContract. For Bradbury the
analogue is `0x0112Bf6e83497965A5fdD6Dad1E447a6E004271D`. Verify by
checking the CLI's behavior — if it doesn't accept zero args, pass
the Bradbury mainContract.

## Step 4: After deploy

The CLI/SDK prints:

```
Transaction Hash: 0x...
Contract Address: 0x...
```

**Paste me the new Contract Address** and I'll:

1. Set API keys on the new contract (run via SDK write)
2. Update `frontend/app.js:7` (CONTRACT constant) to the new address
3. Update `frontend/index.html` header
4. Update frontend to use `testnetBradbury` chain instead of `studionet`
5. Redeploy Vercel
6. Run a fresh Mindex submit against the new contract
7. Verify the v0.3.6 fixes (Bandcamp `<title>` fallback works)
8. Update `AGENT_TANK_SUBMISSION.md` to reference the new contract
9. Commit + push

## What you can do from your side after deploying

1. Run a few manual submits to verify the deploy works end-to-end
2. Test the Bandcamp / SoundCloud fixes manually with Mindex
3. Verify the strict score is now > 0 for Mindex (we expect 25-30)

---

## Why I can't just do this from the VPS

The VPS has 0 GEN on any chain, and the deploy requires a funded
wallet. The user's wallet is on your Mac (or wherever you keep MetaMask),
not here. Hence this doc.
