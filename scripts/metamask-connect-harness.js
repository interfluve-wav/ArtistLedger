// Harness: verify ArtistLedger "real wallet" path against the vendored genlayer-sdk
// Stubs window.ethereum (MetaMask) + the studio RPC, then drives:
//   1. client.connect('studionet','npm')   -> addEthereumChain + requestSnaps
//   2. eth_requestAccounts                  -> real address
//   3. writeContract with per-call json-rpc account -> eth_sendTransaction forwarded to provider
"use strict";
const fs = require("fs");

const captured = [];
const STUDIO_RPC = "https://studio.genlayer.com/api";

const SCHEMA = {
  methods: {
    register_artist: {
      params: [
        ["did", "str"], ["name", "str"], ["audio_hash", "bytes"], ["source_urls", "dict"],
        ["wallet", "str"], ["verification_source_1", "str"], ["verification_handle_1", "str"],
        ["verification_source_2", "str"], ["verification_handle_2", "str"],
        ["require_two_source", "bool"], ["ownership_token", "str"], ["ownership_proofs", "dict"],
      ],
    },
  },
};

// --- fake MetaMask provider, records every request ---
const MM_ACCOUNT = "0x4e82cbc66d6c7a3e0a2c9288b1fb510ed7c347db";
global.window = {
  ethereum: {
    isMetaMask: true,
    request: async ({ method, params }) => {
      captured.push({ method, params });
      switch (method) {
        case "eth_chainId": return "0x1"; // simulate: wallet sits on Ethereum mainnet first
        case "wallet_getSnaps": return {}; // no snaps installed yet
        case "wallet_addEthereumChain": return null;
        case "wallet_switchEthereumChain": return null;
        case "wallet_requestSnaps": return { "npm:genlayer-wallet-plugin": { ok: true } };
        case "eth_requestAccounts": return [MM_ACCOUNT];
        case "eth_sendTransaction": return "0x" + "ab".repeat(32);
        default:
          throw new Error("unexpected wallet method: " + method);
      }
    },
  },
};

// --- fake studio RPC node (non-wallet methods go here via the client transport) ---
global.fetch = async (url, opts) => {
  const body = JSON.parse(opts.body);
  let result;
  switch (body.method) {
    case "eth_chainId": result = "0xF1E7"; break;
    case "gen_getContractSchema": result = SCHEMA; break;
    case "gen_getTransactionCount":
    case "eth_getTransactionCount": result = "0x0"; break;
    case "eth_gasPrice": result = "0x3b9aca00"; break;
    case "eth_estimateGas": result = "0x30d40"; break;
    case "eth_getTransactionReceipt":
      result = { transactionHash: body.params && body.params[0], transactionIndex: "0x0", blockNumber: "0x1", blockHash: "0x" + "cc".repeat(32), from: MM_ACCOUNT, to: "0xb7278A61aa25c888815aFC32Ad3cC52fF24fE575", cumulativeGasUsed: "0x5208", gasUsed: "0x5208", logs: [], status: "0x1", type: "0x0" };
      break;
    default:
      result = "0x"; // opaque fallback
  }
  return { ok: true, json: async () => ({ jsonrpc: "2.0", id: body.id, result }) };
};

// --- load the vendored SDK bundle (IIFE ends with window.GenLayerSDK = ...) ---
eval(fs.readFileSync("/root/projects/ArtistLedger/frontend/lib/genlayer-sdk.js", "utf8"));
const GL = window.GenLayerSDK;

(async () => {
  const CONTRACT = "0x214DBC690f02d2651B4564771fB1094D3A1FDB76";
  const assert = (cond, msg) => { if (!cond) { console.error("FAIL:", msg); process.exitCode = 1; } else console.log("ok  :", msg); };

  // 1. provider-only client (NO client-level account) — this is what makes the
  //    transport forward wallet methods to window.ethereum
  const writeClient = GL.createClient({ chain: GL.chains.studionet });
  assert(writeClient && !writeClient.account, "client created without a client-level account");

  // 1a. official GenLayer connect: add studionet chain + install snap
  await writeClient.connect("studionet", "npm");
  const addChain = captured.find(c => c.method === "wallet_addEthereumChain");
  assert(addChain, "wallet_addEthereumChain was called");
  const CHAINID_HEX = "0x" + GL.chains.studionet.id.toString(16);
  assert(addChain && String(addChain.params[0].chainId).toLowerCase() === CHAINID_HEX.toLowerCase(), "studionet chainId 0xF1E7 proposed (got " + (addChain && addChain.params[0].chainId) + ")");
  assert(addChain && addChain.params[0].rpcUrls[0] === STUDIO_RPC, "studionet RPC proposed");
  assert(addChain && addChain.params[0].nativeCurrency && addChain.params[0].nativeCurrency.symbol === "GEN", "GEN native currency proposed");
  const snaps = captured.find(c => c.method === "wallet_requestSnaps");
  assert(snaps && snaps.params["npm:genlayer-wallet-plugin"], "GenLayer snap requested");
  const switched = captured.find(c => c.method === "wallet_switchEthereumChain");
  assert(switched && String(switched.params[0].chainId).toLowerCase() === CHAINID_HEX.toLowerCase(), "switch to studionet requested");

  // 2. real account identity
  const [addr] = await window.ethereum.request({ method: "eth_requestAccounts" });
  assert(addr === MM_ACCOUNT, "wallet returned the real account");

  // 3. writeContract with a PER-CALL json-rpc account (client-level account stays
  //    empty so eth_sendTransaction routes to the wallet)
  captured.length = 0;
  const args = [
    "did:web:caribou.example", "Caribou", "0x" + "11".repeat(32),
    { apple_music: "45464574", musicbrainz: "735e3514-a8ae-401f-af3b-6300df1b8d2c" },
    addr, "apple_music", "45464574", "musicbrainz", "735e3514-a8ae-401f-af3b-6300df1b8d2c",
    false, "ALVERIFY-DEMO1234", { soundcloud: "caribou" },
  ];
  const tx = await writeClient.writeContract({
    address: CONTRACT, functionName: "register_artist", args,
    value: 0n, leaderOnly: false,
    account: { type: "json-rpc", address: addr },
  });
  console.log("tx returned:", tx);
  const send = captured.find(c => c.method === "eth_sendTransaction");
  assert(send, "eth_sendTransaction was sent to the WALLET (not the RPC node)");
  if (send) {
    const p = send.params[0];
    assert(p.from && p.from.toLowerCase() === MM_ACCOUNT.toLowerCase(), "from = real wallet address");
    assert(p.to === "0xb7278A61aa25c888815aFC32Ad3cC52fF24fE575", "to = consensus main contract (addTransaction envelope)");
    assert(p.data && p.data.length > 10, "calldata carries the register_artist envelope");
    console.log("sendTx params:", JSON.stringify({ from: p.from, to: p.to, gas: p.gas, dataLen: p.data.length }, null, 1));
  }

  // 4. control: without a per-call account the SDK must fail loudly (proves the
  //    per-call account is what makes the provider path work)
  captured.length = 0;
  let threw = false;
  try {
    await writeClient.writeContract({ address: CONTRACT, functionName: "register_artist", args, value: 0n, leaderOnly: false });
  } catch (e) { threw = true; console.log("control (no account) threw:", String(e.message || e).slice(0, 90)); }
  assert(threw, "writeContract without account throws (requires per-call account)");

  console.log("\n=== harness done", process.exitCode ? "WITH FAILURES" : "ALL OK", "===");
})();