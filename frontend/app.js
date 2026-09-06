/* ArtistLedger frontend — talks to GenLayer Studio RPC via genlayer-js SDK. */
"use strict";

const CONTRACT = "0x703AdAB82751A9006aFE9c477DC344f8D9CA4384";
const GL = window.GenLayerSDK;

let client = null;      // read-only client (no account)
let walletAddr = null;  // connected wallet address, if any

function $(id) { return document.getElementById(id); }
function shortAddr(a) { return a.slice(0, 6) + "…" + a.slice(-4); }

function replacer(_k, v) { return typeof v === "bigint" ? v.toString() : v; }

function showResult(id, text, cls) {
  const el = $(id);
  el.textContent = text;
  el.className = "result show " + (cls || "");
}

function showError(id, e) {
  showResult(id, "Error: " + (e && e.message ? e.message : String(e)), "err");
}

// ── Source picker ──────────────────────────────────────────────────────
// User picks 2 (or more) sources. Each becomes a (src, handle) row.
const picked = []; // [{src, handle}]

function renderPicked() {
  const root = $("srcRows");
  root.innerHTML = "";
  picked.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "src-row";
    row.innerHTML = `
      <span class="src-name">${p.src.replace(/_/g, " ")}</span>
      <div style="display:flex;gap:6px">
        <input class="mono" data-i="${i}" value="${p.handle.replace(/"/g, '&quot;')}" placeholder="handle or URL">
        <button class="secondary" data-rm="${i}" style="padding:8px 12px">×</button>
      </div>
    `;
    root.appendChild(row);
  });
  // wire up changes
  root.querySelectorAll("input").forEach(inp => {
    inp.addEventListener("input", e => {
      picked[+e.target.dataset.i].handle = e.target.value;
    });
  });
  root.querySelectorAll("button[data-rm]").forEach(btn => {
    btn.addEventListener("click", e => {
      const i = +e.target.dataset.rm;
      const src = picked[i].src;
      picked.splice(i, 1);
      renderPicked();
      // un-toggle the corresponding chip
      const chip = document.querySelector(`#srcPick button[data-src="${src}"]`);
      if (chip) chip.classList.remove("on");
    });
  });
  updateSubmitHint();
}

$("srcPick").addEventListener("click", e => {
  const btn = e.target.closest("button[data-src]");
  if (!btn) return;
  const src = btn.dataset.src;
  const handle = btn.dataset.handle || "";
  if (picked.some(p => p.src === src)) {
    // toggle off
    const i = picked.findIndex(p => p.src === src);
    picked.splice(i, 1);
    btn.classList.remove("on");
  } else {
    picked.push({ src, handle });
    btn.classList.add("on");
  }
  renderPicked();
});

function updateSubmitHint() {
  const hint = $("raSubmitHint");
  if (!walletAddr) {
    hint.textContent = "Click \"Use local account\" above to get started.";
  } else if (picked.length < 1) {
    hint.textContent = "Pick at least 1 source above.";
  } else {
    hint.textContent = `Will sign as ${shortAddr(walletAddr)}`;
  }
}

// ── RPC helpers ────────────────────────────────────────────────────────

async function rpcRead(fnName, args) {
  if (!client) throw new Error("client not ready");
  return client.readContract({
    address: CONTRACT,
    functionName: fnName,
    args,
    jsonSafeReturn: true,
  });
}

function hexToBytesArg(s) {
  s = s.trim();
  if (s.toLowerCase().startsWith("0x")) s = s.slice(2);
  if (!/^[0-9a-fA-F]+$/.test(s)) throw new Error("audio hash must be hex");
  if (s.length !== 64) throw new Error("audio hash must be 32 bytes (64 hex chars)");
  return "0x" + s.toLowerCase();
}

// ── Read panels ────────────────────────────────────────────────────────

window.queryArtist = async () => {
  showResult("artistResult", "Querying…");
  try {
    const r = await rpcRead("get_artist", [$("artistWallet").value.trim()]);
    showResult("artistResult", JSON.stringify(r, null, 2), "ok");
  } catch (e) { showError("artistResult", e); }
};

window.queryVerified = async () => {
  showResult("vhResult", "Querying…");
  try {
    const h = hexToBytesArg($("vhHash").value);
    const r = await rpcRead("is_verified_human", [h]);
    showResult("vhResult", JSON.stringify(r, null, 2), "ok");
  } catch (e) { showError("vhResult", e); }
};

// ── Wallet connect ─────────────────────────────────────────────────────

function writeClientWithAccount(account) {
  client = GL.createClient({ chain: GL.chains.studionet, account });
}

const LS_KEY = "artistledger.localAccountPk";

$("localAcctBtn").addEventListener("click", async () => {
  try {
    let pk = localStorage.getItem(LS_KEY);
    let account;
    if (pk) {
      account = GL.createAccount(pk);
    } else {
      pk = GL.generatePrivateKey();
      account = GL.createAccount(pk);
      localStorage.setItem(LS_KEY, pk);
    }
    walletAddr = account.address;
    writeClientWithAccount(account);
    $("walletLabel").textContent = shortAddr(walletAddr) + " (local)";
    $("walletLabel").title = walletAddr;
    updateSubmitHint();
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
    $("walletLabel").textContent = shortAddr(walletAddr);
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
    client = GL.createClient({ chain: GL.chains.studionet, provider: window.ethereum });
    updateSubmitHint();
  } catch (e) {
    $("walletLabel").textContent = "Connect failed: " + (e.message || e);
  }
});

// ── Send registration ──────────────────────────────────────────────────

// Map our short source names to the contract's expected 13-enum values.
function toContractSrc(s) {
  const map = {
    apple_music: "apple_music",
    musicbrainz: "musicbrainz",
    bandcamp: "bandcamp_url",
    soundcloud: "soundcloud_url",
    instagram: "instagram",
    lastfm: "lastfm",
    website: "website",
    tiktok: "tiktok",
  };
  return map[s] || s;
}

// Render a friendly result panel from the receipt's evidence + return value.
function renderResult(receipt) {
  const r = receipt;
  let score = null;
  let verdict = "?";
  let matchCount = 0;
  let sourcesMatched = [];
  let tiers = [];
  let llmBonus = 0;
  let evidence = null;

  // Walk the leader receipt for the result + evidence
  for (const lr of r.consensus_data.leader_receipt) {
    if (lr.execution_result === "ERROR") continue;
    // The contract's return value
    if (lr.result && lr.result.payload && lr.result.payload.readable) {
      const txt = lr.result.payload.readable;
      // "Verified (78)" or "Not verified (15)"
      const m = txt.match(/\((\d+)\)/);
      if (m) score = +m[1];
      verdict = txt.includes("Verified") ? "verified" : "not_verified";
    }
    // The Evidence object
    const eq = lr.eq_outputs || {};
    for (const k of Object.keys(eq)) {
      const payload = eq[k].payload;
      if (payload && payload.readable) {
        try {
          // The readable is a stringified JSON object (no spaces between fields, GenVM quirk)
          const normalized = payload.readable.replace(/"\s*"/g, '","');
          evidence = JSON.parse("{" + normalized + "}");
        } catch (e) {
          // fallback: try parsing directly
          try { evidence = JSON.parse(payload.readable); } catch (e2) { /* skip */ }
        }
      }
    }
  }

  if (evidence) {
    matchCount = Number(evidence.verification_match_count || 0);
    if (evidence.acoustid_matched) sourcesMatched.push("AcoustID audio fingerprint");
    if (evidence.spotify_artist_id && (evidence.spotify_verified || (Number(evidence.spotify_popularity) >= 20 && Number(evidence.spotify_followers) >= 1000))) {
      sourcesMatched.push("Spotify");
    }
    if (evidence.apple_music_track_present) sourcesMatched.push("Apple Music track");
    if (evidence.bandcamp_handle) sourcesMatched.push("Bandcamp");
    if (evidence.soundcloud_handle) sourcesMatched.push("SoundCloud");
    if (evidence.instagram_handle) sourcesMatched.push("Instagram");
    if (Number(evidence.lastfm_scrobble_count) >= 100) sourcesMatched.push("Last.fm");
    if (evidence.wallet_age_days && Number(evidence.wallet_age_days) >= 90) sourcesMatched.push("Wallet age ≥90d");
    if (evidence.ens_matches_artist || evidence.farcaster_fname) sourcesMatched.push("Wallet name match");
    if (Number(evidence.isrc_codes?.length || 0) > 0) sourcesMatched.push(`${evidence.isrc_codes.length} ISRC code(s)`);
    llmBonus = Number(evidence.press_narrative_score || 0);
    tiers = [
      ["AcoustID (audio fingerprint)", evidence.acoustid_matched ? 20 : 0, 20],
      ["ISRC codes (MusicBrainz)", `${evidence.isrc_codes?.length || 0} code(s)`, 10],
      ["Spotify", evidence.spotify_artist_id ? "found" : "—", 10],
      ["Apple Music", evidence.apple_music_track_present ? "track found" : "—", 5],
      ["Bandcamp", evidence.bandcamp_handle ? "found" : "—", 3],
      ["SoundCloud", evidence.soundcloud_handle ? `${(Number(evidence.soundcloud_followers)/1000).toFixed(0)}k followers${evidence.soundcloud_verified ? " ✓" : ""}` : "—", 3],
      ["Instagram", evidence.instagram_handle ? "found" : "—", 2],
      ["Last.fm", `${evidence.lastfm_scrobble_count || 0} scrobbles`, 2],
      ["Two-source match", `${matchCount}/2`, 15],
      ["Wallet age", `${evidence.wallet_age_days || 0}d`, 5],
      ["Wallet name", (evidence.ens_matches_artist || evidence.farcaster_fname) ? "match" : "—", 5],
      ["LLM narrative", (llmBonus > 0 ? "+" : "") + llmBonus, 5],
    ];
  }

  const ok = verdict === "verified";
  const panel = $("raResult");
  panel.className = "result show " + (ok ? "ok" : (verdict === "not_verified" ? "" : "err"));

  // Header: big score + verdict line
  let html = `<p class="score">${score ?? "?"}<span style="font-size:14px;color:var(--dim);font-weight:400"> / 100</span></p>`;
  html += `<p class="verdict" style="color:${ok ? "var(--ok)" : "var(--warn)"}">${
    ok ? "✓ Verified — your wallet is tagged as a real human artist"
       : score != null ? `✗ Not verified (score ${score}, need 70)`
       : "Result unknown"
  }</p>`;

  // Why: plain English breakdown
  if (evidence) {
    let whyParts = [];
    if (matchCount >= 2) whyParts.push(`Both claimed sources matched the artist name.`);
    else if (matchCount === 1) whyParts.push(`Only 1 of your 2 claimed sources matched. Add a different source to bump the score.`);
    else whyParts.push(`Neither claimed source could be bound to the artist name. Try sources you actually own.`);
    if (sourcesMatched.length > 0) whyParts.push(`Strong signals: ${sourcesMatched.join(", ")}.`);
    if (llmBonus > 0) whyParts.push(`LLM judge gave +${llmBonus} for consistent press narrative.`);
    if (llmBonus < 0) whyParts.push(`LLM judge gave ${llmBonus} for weak/contradictory narrative.`);
    html += `<p class="why">${whyParts.join(" ")}</p>`;
  }

  // Per-tier breakdown in <details>
  if (tiers.length > 0) {
    html += `<details><summary>Show the per-source breakdown</summary><div class="tiers">`;
    for (const [label, val, max] of tiers) {
      html += `<div class="tier"><span>${label}</span><b>${val}</b></div>`;
    }
    html += `</div></details>`;
  }

  // Receipt hash for the curious
  if (r.hash) {
    html += `<div class="raw">tx hash: ${r.hash}\nresult_name: ${r.result_name}\nstatus_name: ${r.status_name}</div>`;
  }

  panel.innerHTML = html;
}

window.sendRegister = async () => {
  if (!walletAddr) { showError("raResult", new Error("Click \"Use local account\" first.")); return; }
  if (picked.length < 1) { showError("raResult", new Error("Pick at least 1 source.")); return; }

  // Build the contract args. The first two picked sources become vs1/vh1 and vs2/vh2.
  // Audio hash is hardcoded to a default since the user didn't provide one (AcoustID
  // lookup will simply fail to match, and the other tiers still run).
  const name = $("raName").value.trim();
  if (!name) { showError("raResult", new Error("Artist name is required.")); return; }

  const vs1 = picked[0] ? toContractSrc(picked[0].src) : "";
  const vh1 = picked[0] ? picked[0].handle : "";
  const vs2 = picked[1] ? toContractSrc(picked[1].src) : "";
  const vh2 = picked[1] ? picked[1].handle : "";

  // Build a source_urls dict from the picked entries too (for the leader's tier-2 checks)
  const sourceUrls = {};
  for (const p of picked) {
    // The contract's leader_collect looks at top-level keys like bandcamp/soundcloud/instagram/lastfm
    // and uses them as handles/URLs
    sourceUrls[p.src] = p.handle;
  }

  showResult("raResult", "Submitting… (this runs live API checks across all sources — 1-2 minutes)");
  try {
    const audioHash = "0x" + "11".repeat(32); // default placeholder; AcoustID will return no match
    const tx = await client.writeContract({
      address: CONTRACT,
      functionName: "register_artist",
      args: [
        "did:web:" + name.toLowerCase().replace(/\s+/g, "") + ".example",
        name,
        audioHash,
        sourceUrls,
        walletAddr,    // claim the connected wallet is this artist
        vs1, vh1,
        vs2, vh2,
        $("raStrict").checked,
      ],
      value: 0n,
      leaderOnly: false,
    });
    showResult("raResult", "Submitted. Waiting for consensus…\ntx: " + JSON.stringify(tx, replacer, 2), "ok");

    // Wait for the receipt
    const receipt = await client.waitForTransactionReceipt({
      hash: tx,
      status: "FINALIZED",
      retries: 60,
      interval: 4000,
    });
    renderResult(receipt);
  } catch (e) { showError("raResult", e); }
};

// ── Boot ──────────────────────────────────────────────────────────────

// Show "Connect wallet" only if a browser-injected wallet is present.
// On studionet, "Use local account" is the recommended path; many users
// have 1inch/Trust/MetaMask mobile that don't inject window.ethereum.
if (typeof window !== "undefined" && window.ethereum) {
  $("connectBtn").style.display = "";
}

(async function boot() {
  try {
    client = GL.createClient({ chain: GL.chains.studionet });
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
    $("rpcStatus").textContent = "Connected — methods: " + methods;
    await rpcRead("is_verified_human", ["0x1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff"]);
  } catch (e) {
    $("rpcDot").classList.add("err");
    $("rpcStatus").textContent = "RPC unreachable: " + (e.message || e);
  }
  updateSubmitHint();
})();
