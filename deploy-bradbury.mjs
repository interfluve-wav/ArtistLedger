// deploy-bradbury.mjs — Deploy ArtistLedger v0.3.6 to GenLayer Bradbury Testnet.
//
// Usage on your Mac:
//   1. cd ArtistLedger
//   2. git checkout final-calls && git pull
//   3. export DEPLOYER_PK=0x<your private key for 0xfCeb2B7...>
//   4. node deploy-bradbury.mjs
//
// Output:
//   Transaction Hash: 0x...
//   Contract Address: 0x...   <-- paste this back to Hermes
//
// Requires: Node 18+, the genlayer-js SDK at the global path
// /usr/local/lib/node_modules/genlayer/node_modules/genlayer-js

import { readFileSync } from 'node:fs';
import {
  createClient,
  createAccount,
} from '/usr/local/lib/node_modules/genlayer/node_modules/genlayer-js/dist/index.js';

const BRADBURY_RPC = 'https://rpc-bradbury.genlayer.com';
const BRADBURY_MAIN_CONTRACT = '0x0112Bf6e83497965A5fdD6Dad1E447a6E004271D';
const CHAIN_ID = 4221;

const pk = process.env.DEPLOYER_PK;
if (!pk) {
  console.error('Set DEPLOYER_PK=<hex private key, with or without 0x prefix>');
  process.exit(1);
}

// Create a local account (the SDK signs locally with the provided pk;
// the key never leaves your machine).
const account = createAccount(pk);
console.log(`Deployer: ${account.address}`);
console.log(`Balance check on Bradbury...`);

const client = createClient({
  chain: {
    id: CHAIN_ID,
    name: 'Bradbury',
    rpcUrls: { default: { http: [BRADBURY_RPC] } },
    nativeCurrency: { name: 'GEN', symbol: 'GEN', decimals: 18 },
  },
  account,
});

// Read the contract source.
const contractSrc = readFileSync(
  new URL('./contracts/ProvenanceRegistry.py', import.meta.url),
  'utf8'
);
console.log(`Contract source: ${contractSrc.length} bytes`);

// GenLayer deploy protocol: send the contract source as tx data
// to the consensusMainContract. The node compiles it and creates
// a new contract at a derived address. No constructor args
// required (ProvenanceRegistry takes none).
const dataHex = '0x' + Buffer.from(contractSrc, 'utf8').toString('hex');

console.log(`\nSending deploy tx to ${BRADBURY_MAIN_CONTRACT}...`);
let txHash;
try {
  txHash = await client.sendTransaction({
    to: BRADBURY_MAIN_CONTRACT,
    value: 0n,
    data: dataHex,
  });
} catch (e) {
  console.error('Deploy failed:', e.message || e);
  if (e.cause) console.error('Cause:', e.cause);
  if (e.details) console.error('Details:', e.details);
  process.exit(1);
}
console.log(`\n✅ tx submitted: ${txHash}`);

// Poll for receipt.
console.log('Waiting for FINALIZED receipt (polls every 4s, up to 4 min)...');
let receipt = null;
for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 4000));
  try {
    const r = await client.getTransaction({ hash: txHash });
    if (r && (r.blockNumber || r.status === 'FINALIZED' || r.status_name === 'FINALIZED')) {
      receipt = r;
      break;
    }
  } catch (e) {
    // keep polling — RPC may transiently 404 before indexing
  }
  process.stdout.write('.');
}
console.log();

if (!receipt) {
  console.error('Timed out waiting for receipt after 4 minutes.');
  console.error(`Check tx on explorer: https://explorer-bradbury.genlayer.com`);
  console.error(`Or query directly:`);
  console.error(`  curl https://rpc-bradbury.genlayer.com/api \\`);
  console.error(`    -X POST -H "Content-Type: application/json" \\`);
  console.error(`    -d '{"jsonrpc":"2.0","method":"eth_getTransactionReceipt","params":["${txHash}"],"id":1}'`);
  process.exit(1);
}

console.log('\n=== Receipt ===');
console.log(JSON.stringify(
  receipt,
  (_, v) => typeof v === 'bigint' ? v.toString() : v,
  2
));

// Extract contract address from receipt's `to` field (deploy creates
// a new contract at the `to` address) or from contractAddress field.
const newContract =
  receipt.contractAddress ||
  receipt.to ||
  '(check receipt fields above)';

console.log(`\n========================================`);
console.log(`PASTE THIS BACK TO HERMES:`);
console.log(`  Contract Address: ${newContract}`);
console.log(`  Tx Hash:          ${txHash}`);
console.log(`========================================`);
