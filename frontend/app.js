/* ArtistLedger frontend — talks to GenLayer Studio RPC via genlayer-js SDK. */
"use strict";

const CONTRACT = "0x703AdAB82751A9006aFE9c477DC344f8D9CA4384";
const GL = window.GenLayerSDK;

let client = null;      // read-only client (no account)
let walletAddr = null;  // connected wallet address, if any

function $(id) { return document.getElementById(id); }

function showResult(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = "result show " + (cls || "");
}

function hexToBytesArg(s) {
  // Accept 0x-prefixed or raw hex; strip 0x for SDK bytes handling.
  s = s.trim();
  if (s.toLowerCase().startsWith("0x")) s = s.slice(2);
  if (!/^[0-9a-fA-F]+$/.test(s)) throw new Error("audio hash must be hex");
  if (s.length !== 64) throw new Error("audio hash must be 32 bytes (64 hex chars)");
  return "0x" + s.toLowerCase();
}

async function rpcRead(fnName, args) {
  if (!client) throw new Error("client not ready");
  return client.readContract({
    address: CONTRACT,
    functionName: fnName,
    args,
    jsonSafeReturn: true,
  });
}

async function safeRead(btnLabel, fn, outId) {
  showResult(outId, "Querying…");
  try {
    const r = await fn();
    showResult(outId, JSON.stringify(r, null, 2), "ok");
  } catch (e) {
    showResult(outId, "ERROR: " + (e && e.message ? e.message : String(e)), "err");
  }
}

// ── Read panels ───────────────────────────────────────────────────────────

window.queryArtist = () => safeRead("artist", () =>
  rpcRead("get_artist", [ $("artistWallet").value.trim() ]), "artistResult");

window.queryVerified = () => safeRead("vh", async () => {
  const h = hexToBytesArg($("vhHash").value);
  return rpcRead("is_verified_human", [ h ]);
}, "vhResult");

window.queryRelease = () => safeRead("rel", async () => {
  const h = hexToBytesArg($("relHash").value);
  return rpcRead("get_release", [ h ]);
}, "relResult");

window.queryDispute = () => safeRead("disp", async () => {
  const h = hexToBytesArg($("dispHash").value);
  return rpcRead("get_dispute", [ h ]);
}, "dispResult");

// ── Wallet connect ────────────────────────────────────────────────────────

function shortAddr(a) { return a.slice(0, 6) + "…" + a.slice(-4); }

function writeClientWithAccount(account) {
  client = GL.createClient({ chain: GL.chains.studionet, account });
}

// Local account mode: key generated in-browser, kept in localStorage.
// Safe for studionet test accounts (no gas, no real funds).
const LS_KEY = "artistledger.localAccountPk";

$("localAcctBtn").addEventListener("click", async () => {
  try {
    let pk = localStorage.getItem(LS_KEY);
    let account = GL.createAccount(pk || undefined);
    if (!pk) {
      // createAccount without args generated a key; regenerate to capture it.
      // SDK exposes generatePrivateKey separately.
      pk = GL.generatePrivateKey();
      account = GL.createAccount(pk);
      localStorage.setItem(LS_KEY, pk);
    }
    walletAddr = account.address;
    writeClientWithAccount(account);
    $("walletLabel").textContent = shortAddr(walletAddr) + " (local)";
    $("walletLabel").title = walletAddr;
  } catch (e) {
    $("walletLabel").textContent = "Local account failed: " + (e.message || e);
  }
});

$("connectBtn").addEventListener("click", async () => {
  if (!window.ethereum) {
    $("walletLabel").textContent = "No wallet detected (window.ethereum missing)";
    return;
  }
  try {
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    walletAddr = accounts[0];
    $("walletLabel").textContent = walletAddr.slice(0, 6) + "…" + walletAddr.slice(-4);
    // Switch to Studio Network chain
    try {
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: "0xf22f" }],
      });
    } catch (e) {
      if (e && e.code === 4902) {
        await window.ethereum.request({
          method: "wallet_addEthereumChain",
          params: [{
            chainId: "0xf22f",
            chainName: "GenLayer Studio Network",
            nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 },
            rpcUrls: ["https://studio.genlayer.com/api"],
          }],
        });
      }
    }
    // Rebuild client with the provider so writes get signed by the wallet.
    client = GL.createClient({ chain: GL.chains.studionet, provider: window.ethereum });
  } catch (e) {
    $("walletLabel").textContent = "Connect failed: " + (e.message || e);
  }
});

// ── Write panels ──────────────────────────────────────────────────────────

window.sendRegister = async () => {
  if (!walletAddr) { showResult("raResult", "Connect a wallet first.", "err"); return; }
  showResult("raResult", "Submitting… (this runs live API checks through consensus — can take minutes)");
  try {
    const sources = JSON.parse($("raSources").value);
    const hash = hexToBytesArg($("raHash").value);
    const tx = await client.writeContract({
      address: CONTRACT,
      functionName: "register_artist",
      args: [
        $("raDid").value.trim(),
        $("raName").value.trim(),
        hash,
        sources,
        $("raWallet").value.trim(),
        $("raVs1").value.trim(),
        $("raVh1").value.trim(),
        $("raVs2").value.trim(),
        $("raVh2").value.trim(),
        $("raTwoSource").value === "true",
      ],
      value: 0n,
      leaderOnly: false,
    });
    showResult("raResult", "Transaction submitted.\n\n" + JSON.stringify(tx, replacer, 2), "ok");
  } catch (e) {
    showResult("raResult", "ERROR: " + (e && e.message ? e.message : String(e)), "err");
  }
};

window.sendDispute = async () => {
  if (!walletAddr) { showResult("dResult", "Connect a wallet first.", "err"); return; }
  showResult("dResult", "Submitting…");
  try {
    const hash = hexToBytesArg($("dHash").value);
    const tx = await client.writeContract({
      address: CONTRACT,
      functionName: "dispute",
      args: [ hash, $("dClaim").value.trim(), $("dUrl").value.trim() ],
      value: 0n,
      leaderOnly: false,
    });
    showResult("dResult", "Transaction submitted.\n\n" + JSON.stringify(tx, replacer, 2), "ok");
  } catch (e) {
    showResult("dResult", "ERROR: " + (e && e.message ? e.message : String(e)), "err");
  }
};

function replacer(_k, v) { return typeof v === "bigint" ? v.toString() : v; }

// ── Boot ──────────────────────────────────────────────────────────────────

(async function boot() {
  try {
    client = GL.createClient({ chain: GL.chains.studionet });
    // Studio RPC expects gen_getContractSchema with a plain string param.
    let schema;
    try {
      schema = await client.request({
        method: "gen_getContractSchema",
        params: [CONTRACT],
      });
    } catch (e) {
      schema = await client.getContractSchema({ address: CONTRACT });
    }
    const methods = Object.keys((schema && schema.methods) || {}).join(", ");
    $("rpcDot").classList.add("on");
    $("rpcStatus").textContent = "Connected — contract live, methods: " + methods;
    // Warm read to prove the read path works.
    await rpcRead("is_verified_human", ["0x1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"]);
  } catch (e) {
    $("rpcDot").classList.add("err");
    $("rpcStatus").textContent = "RPC unreachable: " + (e.message || e);
  }
})();
