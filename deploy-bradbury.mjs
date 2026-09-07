// deploy-bradbury.mjs — Deploy ArtistLedger v0.3.6 to GenLayer Bradbury Testnet.
//
// Usage on your Mac:
//   1. cd ArtistLedger
//   2. git checkout final-calls && git pull
//   3. npm install   (so node_modules/genlayer-js exists)
//   4. export DEPLOYER_PK="0x<your private key for 0xfCeb2B7...>"
//   5. node deploy-bradbury.mjs
//
// Output:
//   Transaction Hash: 0x...
//   Contract Address: 0x...   <-- paste this back to Hermes
//
// Requires: Node 18+.

import { readFileSync } from 'node:fs';
import {
  createClient,
  createAccount,
  chains,
} from 'genlayer-js';

const BRADBURY = chains.testnetBradbury;  // pre-configured in the SDK
const pk = process.env.DEPLOYER_PK;
if (!pk) {
  console.error('Set DEPLOYER_PK="0x<hex private key>"');
  process.exit(1);
}

const account = createAccount(pk);
console.log(`Deployer: ${account.address}`);

// Use the SDK's pre-configured testnetBradbury chain — it has the
// full consensusMainContract { address, abi } object already wired.
const client = createClient({
  chain: BRADBURY,
  account,
});

console.log(`Chain: ${BRADBURY.name} (id ${BRADBURY.id})`);
console.log(`Consensus main contract: ${BRADBURY.consensusMainContract?.address}`);

// Read the contract source as UTF-8 text.
const contractCode = readFileSync(
  new URL('./contracts/ProvenanceRegistry.py', import.meta.url),
  'utf8'
);
console.log(`Contract source: ${contractCode.length} bytes`);

console.log(`\nDeploying...`);
let txHash;
try {
  // The SDK's deployContract wraps the consensus contract's deploy
  // function with proper ABI encoding. ProvenanceRegistry has no
  // constructor args.
  txHash = await client.deployContract({
    code: contractCode,
    args: [],
    leaderOnly: false,
  });
} catch (e) {
  console.error('Deploy failed:', e.message || e);
  if (e.cause) console.error('Cause:', e.cause);
  if (e.details) console.error('Details:', e.details);
  process.exit(1);
}
console.log(`\n✅ tx submitted: ${txHash}`);

// Poll for receipt.
console.log('Waiting for FINALIZED receipt (polls every 5s, up to ~4 min)...');
let receipt = null;
for (let i = 0; i < 50; i++) {
  await new Promise((r) => setTimeout(r, 5000));
  try {
    const r = await client.waitForTransactionReceipt({
      hash: txHash,
      retries: 1,
      interval: 1000,
    });
    if (r) { receipt = r; break; }
  } catch (e) {
    // keep polling
  }
  process.stdout.write('.');
}
console.log();

if (!receipt) {
  console.error('Timed out waiting for receipt after ~4 minutes.');
  console.error(`Check tx on explorer: https://explorer-bradbury.genlayer.com`);
  process.exit(1);
}

console.log('\n=== Receipt ===');
console.log(JSON.stringify(
  receipt,
  (_, v) => typeof v === 'bigint' ? v.toString() : v,
  2
));

const newContract =
  receipt.data?.contract_address ||
  receipt.txDataDecoded?.contractAddress ||
  receipt.contractAddress ||
  '(check receipt fields above)';

console.log(`\n========================================`);
console.log(`PASTE THIS BACK TO HERMES:`);
console.log(`  Contract Address: ${newContract}`);
console.log(`  Tx Hash:          ${txHash}`);
console.log(`========================================`);
