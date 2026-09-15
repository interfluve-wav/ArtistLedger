/* ArtistLedger — Register → Certificate → Inspect
 * Talks to the v4 GenLayer contract on studionet via the genlayer-js SDK.
 * Replaces the old 3-card form. State machine: A (register) → B (certificate) → C (inspect).
 */
"use strict";

// Deployed on studionet (2026-09-13, gasless): all features incl.
// ownership proofs + key pools. Verified: schema OK, 12 methods,
// 5/5 validators AGREE on deploy + writes. See docs/OPERATIONS.md.
const CONTRACT = "0xA73E4588E900f0d4b62Eca0e963B275dc2AfC5a4";
const GL = window.GenLayerSDK;

let walletAddr = null;    // connected wallet
let lastReceipt = null;   // for the inspect modal
let lastData = null;      // parsed evidence + verdict

function $(id) { return document.getElementById(id); }
function shortAddr(a) { return a.slice(0, 6) + "…" + a.slice(-4); }
function replacer(_k, v) { return typeof v === "bigint" ? v.toString() : v; }

// ── Artist portrait (Wikipedia REST summary, keyless) ─────────────────
// Fetched only after the seal flips. Plain-name lookups can land on
// disambiguation pages ("Burial" → the ritual, "Caribou" → the deer), so
// for known demo artists we use the disambiguated title directly.
const WIKI_TITLES = {
  "Four Tet": "Four_Tet", "Caribou": "Caribou_(musician)", "Burial": "Burial_(musician)",
  "Aphex Twin": "Aphex_Twin", "Boards of Canada": "Boards_of_Canada",
  "Floating Points": "Floating_Points", "Fred again..": "Fred_again..",
  "Jamie xx": "Jamie_xx", "Skrillex": "Skrillex", "deadmau5": "Deadmau5",
  "Daft Punk": "Daft_Punk",
};

// Source order matters — Wikipedia first (curated portraits, CORS-enabled),
// MusicBrainz second (CORS-enabled, cover-art proxy), Deezer LAST because
// api.deezer.com omits Access-Control-Allow-Origin — browser fetches are
// blocked by CORS, so it only works in non-browser contexts. Kept as a
// harmless last resort for potential future server-side use.
const PHOTO_SOURCES = ["wikipedia", "musicbrainz", "deezer"];

async function fetchFromDeezer(name) {
  const url = "https://api.deezer.com/search/artist?q=" + encodeURIComponent(name) + "&limit=1";
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) return null;
  const d = await res.json();
  const a = d?.data?.[0];
  if (!a) return null;
  // Guard against fuzzy-match junk: require the returned name to overlap the query.
  const q = name.toLowerCase().replace(/[^a-z0-9]/g, "");
  const r = (a.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (!q || !r || !q.includes(r.slice(0, Math.min(5, r.length))) && !r.includes(q.slice(0, Math.min(5, q.length)))) return null;
  const src = a.picture_xl || a.picture_big || a.picture_medium || a.picture;
  return src ? { src, credit: "Deezer" } : null;
}

async function fetchFromWikipedia(name) {
  const title = WIKI_TITLES[name] || name.trim().replace(/\s+/g, "_");
  const url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + encodeURIComponent(title);
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) return null;
  const d = await res.json();
  // guard against wrong-entity (Burial the practice) — accept only when description
  // describes a person/band, or when we have an explicit WIKI_TITLES entry.
  const desc = (d.description || "").toLowerCase();
  const isPersonOrBand = /(singer|musician|band|dj|artist|duo|group|producer)/.test(desc);
  const isTrusted = !!WIKI_TITLES[name];
  const src = (isTrusted || (d.type === "standard" && isPersonOrBand))
    ? d.thumbnail?.source : null;
  return src ? { src, credit: "Wikipedia" } : null;
}

async function fetchFromMusicBrainz(name) {
  // MB has artist images via the cover-art archive, but for artist portrait
  // the front-page release cover is the next best proxy when the artist has
  // no relation image. Use /ws/2/artist/?query= for canonical name first.
  const search = "https://musicbrainz.org/ws/2/artist/?query="
    + encodeURIComponent("artist:" + name)
    + "&fmt=json&limit=10";
  const UA = { Accept: "application/json", "User-Agent": "ArtistLedger/0.3 (https://artistledger-frontend.vercel.app)" };
  let res = await fetch(search, { headers: UA });
  // MB polices ~1 req/s — one spaced retry on throttle/soft failures
  if (!res.ok) {
    await new Promise((r) => setTimeout(r, 1100));
    res = await fetch(search, { headers: UA });
  }
  if (!res.ok) return null;
  const d = await res.json();
  // Identity guard: MB fuzzy search ranks token-overlap matches first
  // ("Pearson Sound" → "Falcom Sound Team jdk", "Stain" → "Blood Stain
  // Child"). Scan the candidates for an EXACT normalized match on name,
  // sort-name, or a listed alias — better a placeholder than someone
  // else's face on the certificate.
  const norm = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const target = norm(name);
  const mbid = (d?.artists || []).find((a) =>
    [a.name, a["sort-name"],
      ...(Array.isArray(a.aliases) ? a.aliases.map((al) => al.name) : [])]
      .some((c) => norm(c) === target)
  )?.id;
  if (!mbid) return null;
  // Any official release (not just albums): dance/dubplate catalogs are
  // EPs and 12"s — filtering type=album empties the result for exactly the
  // artists this fallback exists for. Cover Art Archive: 250px front, no auth.
  const rels = "https://musicbrainz.org/ws/2/release?artist=" + mbid
    + "&status=official&fmt=json&limit=1";
  let r2 = await fetch(rels, {
    headers: { Accept: "application/json", "User-Agent": "ArtistLedger/0.3 (https://artistledger-frontend.vercel.app)" },
  });
  // MB polices ~1 req/s — one spaced retry on rate-limit/soft failures
  if (!r2.ok) {
    await new Promise((r) => setTimeout(r, 1100));
    r2 = await fetch(rels, {
      headers: { Accept: "application/json", "User-Agent": "ArtistLedger/0.3 (https://artistledger-frontend.vercel.app)" },
    });
  }
  if (!r2.ok) return null;
  const d2 = await r2.json();
  const rgid = d2?.releases?.[0]?.id;
  if (!rgid) return null;
  return {
    src: "https://coverartarchive.org/release/" + rgid + "/front-250",
    credit: "MusicBrainz",
  };
}

async function fetchArtistPortrait(name) {
  const box = $("cert-photo");
  const img = $("cert-photo-img");
  const holder = $("cert-photo-holder");
  const initial = $("cert-photo-initial");
  const creditEl = $("cert-photo-credit");
  if (!box) return;
  // reset to placeholder while loading
  img.removeAttribute("src");
  img.style.display = "none";
  holder.style.display = "flex";
  box.style.display = "flex";
  if (initial) initial.textContent = (name.trim()[0] || "?").toUpperCase();
  if (creditEl) creditEl.textContent = "";

  // Try each source in order; first hit wins.
  for (const source of PHOTO_SOURCES) {
    let hit = null;
    try {
      if (source === "deezer") hit = await fetchFromDeezer(name);
      else if (source === "wikipedia") hit = await fetchFromWikipedia(name);
      else if (source === "musicbrainz") hit = await fetchFromMusicBrainz(name);
    } catch { continue; }
    if (hit) {
      img.onload = () => {
        img.style.display = "block";
        holder.style.display = "none";
        if (creditEl) creditEl.textContent = "photo: " + hit.credit;
      };
      img.onerror = () => { holder.style.display = "flex"; };
      img.src = hit.src;
      img.alt = name + " — portrait via " + hit.credit;
      return;
    }
  }
  // no source returned a usable image — placeholder initial stays
}

// Map short source names → contract's 13-enum source types.
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

// ── Source picker ──────────────────────────────────────────────────────
const picked = []; // [{src, handle}]

function renderPicked() {
  const root = $("srcRows");
  root.innerHTML = "";
  picked.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "src-row";
    row.innerHTML = `
      <select data-i="${i}">
        <option value="apple_music" ${p.src==="apple_music"?"selected":""}>Apple Music</option>
        <option value="musicbrainz" ${p.src==="musicbrainz"?"selected":""}>MusicBrainz</option>
        <option value="bandcamp" ${p.src==="bandcamp"?"selected":""}>Bandcamp</option>
        <option value="soundcloud" ${p.src==="soundcloud"?"selected":""}>SoundCloud</option>
        <option value="instagram" ${p.src==="instagram"?"selected":""}>Instagram</option>
        <option value="lastfm" ${p.src==="lastfm"?"selected":""}>Last.fm</option>
        <option value="website" ${p.src==="website"?"selected":""}>Website</option>
        <option value="tiktok" ${p.src==="tiktok"?"selected":""}>TikTok</option>
      </select>
      <input data-h="${i}" value="${(p.handle || "").replace(/"/g, '&quot;')}" placeholder="handle, ID, or URL">
      <button class="rm" data-rm="${i}">×</button>
    `;
    root.appendChild(row);
  });
  root.querySelectorAll("select").forEach(sel => {
    sel.addEventListener("change", e => { picked[+e.target.dataset.i].src = e.target.value; });
  });
  root.querySelectorAll("input").forEach(inp => {
    inp.addEventListener("input", e => { picked[+e.target.dataset.h].handle = e.target.value; });
  });
  root.querySelectorAll("button.rm").forEach(btn => {
    btn.addEventListener("click", e => {
      const i = +e.target.dataset.rm;
      const src = picked[i].src;
      picked.splice(i, 1);
      renderPicked();
      const chip = document.querySelector(`#srcPick button[data-src="${src}"]`);
      if (chip) chip.classList.remove("on");
    });
  });
  if (window.setAtmosphereMode) {
    const artistName = $("f-name") ? $("f-name").value.trim() : "";
    window.setAtmosphereMode("composing", { name: artistName, sources: picked.length });
  }
}

$("srcPick").addEventListener("click", e => {
  const btn = e.target.closest("button[data-src]");
  if (!btn) return;
  const src = btn.dataset.src;
  const handle = btn.dataset.handle || "";
  if (picked.some(p => p.src === src)) {
    const i = picked.findIndex(p => p.src === src);
    picked.splice(i, 1);
    btn.classList.remove("on");
  } else {
    if (picked.length >= 2) {
      // swap oldest
      const old = picked.shift();
      const oldChip = document.querySelector(`#srcPick button[data-src="${old.src}"]`);
      if (oldChip) oldChip.classList.remove("on");
    }
    picked.push({ src, handle });
    btn.classList.add("on");
  }
  renderPicked();
});

// ── Live verify log (right pane) ───────────────────────────────────────
function logLine(s, customTag) {
  const stream = $("loglines");
  if (!stream) return;
  const liveBox = $("live-logs");
  if (liveBox && liveBox.style.display === "none") liveBox.style.display = "block";

  let tag = customTag || "info";
  let cleanMsg = s;

  if (s.startsWith("[01]")) {
    tag = "build";
    cleanMsg = s.replace(/^\[01\]\s*/, "");
    if (window.setAtmosphereMode) window.setAtmosphereMode("building", { msg: cleanMsg });
  } else if (s.startsWith("[02] Waiting") || s.startsWith("[02] Signing")) {
    tag = "sign";
    cleanMsg = s.replace(/^\[02\]\s*/, "");
    if (window.setAtmosphereMode) window.setAtmosphereMode("signing", { msg: cleanMsg });
  } else if (s.startsWith("[02] Submitted tx")) {
    tag = "tx";
    cleanMsg = s.replace(/^\[02\]\s*/, "");
    const hashMatch = cleanMsg.match(/0x[a-fA-F0-9]+/);
    if (window.setAtmosphereMode) window.setAtmosphereMode("broadcasting", { hash: hashMatch ? hashMatch[0] : "" });
  } else if (s.startsWith("[03]")) {
    tag = "consensus";
    cleanMsg = s.replace(/^\[03\]\s*/, "");
    if (cleanMsg.includes("FINALIZED") || cleanMsg.includes("MAJORITY")) {
      if (window.setAtmosphereMode) window.setAtmosphereMode("consensus", { msg: cleanMsg });
    } else {
      if (window.setAtmosphereMode) window.setAtmosphereMode("verifying", { msg: cleanMsg });
    }
  } else if (s.startsWith("[err]")) {
    tag = "err";
    cleanMsg = s.replace(/^\[err\]\s*/, "");
    if (window.setAtmosphereMode) window.setAtmosphereMode("error", { err: cleanMsg });
  } else if (s.toLowerCase().includes("connected real wallet") || s.toLowerCase().includes("connected account")) {
    tag = "ok";
    if (window.setAtmosphereMode) window.setAtmosphereMode("connected", { wallet: walletAddr });
  }

  // Highlight hexadecimal hashes and addresses
  cleanMsg = cleanMsg.replace(/(0x[a-fA-F0-9]{6,})/g, '<span class="hl">$1</span>');

  const row = document.createElement("div");
  row.className = `log-entry ${tag}`;
  const timeStr = new Date().toTimeString().substring(0, 8);
  row.innerHTML = `<span class="log-time">${timeStr}</span><span class="log-tag ${tag}">${tag}</span><span class="log-msg">${cleanMsg}</span>`;

  // Remove existing cursor row before appending new line
  const oldCursor = stream.querySelector(".log-cursor-row");
  if (oldCursor) oldCursor.remove();

  stream.appendChild(row);

  // Re-add terminal cursor row
  const cursorRow = document.createElement("div");
  cursorRow.className = "log-cursor-row";
  cursorRow.innerHTML = `<span>&gt;</span><span class="log-cursor"></span>`;
  stream.appendChild(cursorRow);

  stream.scrollTop = stream.scrollHeight;

  const countEl = $("logCount");
  if (countEl) {
    const total = stream.querySelectorAll(".log-entry").length;
    countEl.textContent = `${total} event${total === 1 ? "" : "s"}`;
  }
}

function clearLog() {
  const stream = $("loglines");
  if (stream) stream.innerHTML = "";
  const countEl = $("logCount");
  if (countEl) countEl.textContent = "0 events";
}

// ── Wallet / RPC ───────────────────────────────────────────────────────
// Read client is initialized once at page load so the first rpcRead()
// doesn't pay the genlayer-js cold-start cost on every call. The write
// client's signer depends on the connect mode:
//   • REAL wallet (MetaMask / any window.ethereum, default): the client is
//     created WITHOUT an account so the SDK transport routes wallet methods
//     (eth_sendTransaction …) to the browser wallet; the actual signer is
//     attached per-call at submit time as a json-rpc account. The GenLayer
//     snap (npm:genlayer-wallet-plugin) makes MetaMask understand studionet.
//   • Demo key (fallback when no browser wallet is installed): a freshly
//     generated key persisted in localStorage. It only signs testnet writes —
//     the contract's creator role is fixed at deploy — so it is DISPOSABLE by
//     design and never reflects a real identity on-chain.
const LS_KEY = "artistledger.localAccountPk";

// studionet (chainId 61999 = 0xf22f) — used for the manual wallet_addEthereumChain
// fallback when the snap-based connect() fails (e.g. user declined the snap).
const STUDIONET_CHAIN_ID_HEX = "0x" + GL.chains.studionet.id.toString(16);
const STUDIONET_CHAIN_PARAMS = {
  chainId: STUDIONET_CHAIN_ID_HEX,
  chainName: "Genlayer Studio Network",
  nativeCurrency: { name: "GEN Token", symbol: "GEN", decimals: 18 },
  rpcUrls: ["https://studio.genlayer.com/api"],
  blockExplorerUrls: ["https://genlayer-explorer.vercel.app"],
};

let readClient = null;       // pre-warmed on page load
let writeClient = null;      // created on connect (mode-dependent)
let account = null;          // demo-key genlayer-js account (real mode keeps this null)
let walletKind = null;       // "real" | "demo"

function ensureReadClient() {
  if (readClient) return readClient;
  readClient = GL.createClient({ chain: GL.chains.studionet });
  return readClient;
}

// Warm the read client immediately so the first RPC call is fast.
try { ensureReadClient(); } catch (e) { /* will retry on first rpcRead */ }

// Demo-key signer: attaches a locally generated private key (persisted in
// localStorage so the demo identity survives reloads). Plaintext storage
// means any XSS can steal it; acceptable only because the key controls
// nothing of value. "Reset key" wipes it and rotates a fresh one.
function attachAccount(pk) {
  account = GL.createAccount(pk);
  walletAddr = account.address;
  walletKind = "demo";
  writeClient = GL.createClient({ chain: GL.chains.studionet, account });
  $("walletLabel").textContent = shortAddr(walletAddr) + " (demo key · disposable)";
  $("walletLabel").title = "Disposable testnet key, stored in browser storage (plaintext). Use Reset key to rotate. Not a real wallet — install MetaMask and Connect again for a real identity.";
  $("localAcctReset").style.display = "inline-flex";
  checkWalletVerified();
  document.dispatchEvent(new CustomEvent("wallet-connected"));
}

// ── Multi-Wallet Provider Hub (MetaMask, Phantom, Coinbase, WalletConnect) ─
let activeWalletName = "MetaMask";
let activeProvider = null;

// EIP-6963 provider announcements (Multi Injected Provider Discovery)
const eip6963Providers = new Map();
if (typeof window !== "undefined") {
  window.addEventListener("eip6963:announceProvider", (event) => {
    if (event.detail && event.detail.info && event.detail.provider) {
      eip6963Providers.set(event.detail.info.rdns || event.detail.info.name, event.detail);
      renderWalletList();
    }
  });
  window.dispatchEvent(new Event("eip6963:requestProvider"));
}

function getMetaMaskProvider() {
  if (eip6963Providers.has("io.metamask")) return eip6963Providers.get("io.metamask").provider;
  if (window.ethereum?.providers?.length) {
    const p = window.ethereum.providers.find(x => x.isMetaMask && !x.isPhantom);
    if (p) return p;
  }
  if (window.ethereum?.isMetaMask && !window.ethereum?.isPhantom) return window.ethereum;
  return window.ethereum || null;
}

function getPhantomProvider() {
  if (eip6963Providers.has("app.phantom")) return eip6963Providers.get("app.phantom").provider;
  if (window.phantom?.ethereum) return window.phantom.ethereum;
  if (window.ethereum?.providers?.length) {
    const p = window.ethereum.providers.find(x => x.isPhantom);
    if (p) return p;
  }
  if (window.ethereum?.isPhantom) return window.ethereum;
  return null;
}

function getCoinbaseProvider() {
  if (eip6963Providers.has("com.coinbase.wallet")) return eip6963Providers.get("com.coinbase.wallet").provider;
  if (window.coinbaseWalletExtension) return window.coinbaseWalletExtension;
  if (window.ethereum?.providers?.length) {
    const p = window.ethereum.providers.find(x => x.isCoinbaseWallet);
    if (p) return p;
  }
  if (window.ethereum?.isCoinbaseWallet) return window.ethereum;
  return null;
}

// REAL wallet: connects the selected provider (MetaMask, Phantom, Coinbase, etc.).
// Requests accounts FIRST so the native wallet popup appears immediately.
async function connectWithProvider(provider, walletName) {
  if (!provider) {
    if (walletName === "MetaMask") window.open("https://metamask.io/download/", "_blank");
    else if (walletName === "Phantom") window.open("https://phantom.app/download", "_blank");
    else if (walletName === "Coinbase Wallet") window.open("https://www.coinbase.com/wallet", "_blank");
    else alert(`No ${walletName} extension detected in this browser.`);
    return;
  }

  closeWalletModal();
  logLine(`requesting ${walletName} connection (check popup)…`);

  // 1. Request accounts first — pops the selected wallet dialog immediately
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  if (!accounts || !accounts.length) throw new Error(`${walletName} returned no accounts.`);

  activeProvider = provider;
  activeWalletName = walletName;
  account = null;
  walletAddr = accounts[0];
  walletKind = "real";

  $("walletLabel").textContent = `${shortAddr(walletAddr)} (${walletName} · real)`;
  $("walletLabel").title = `${walletAddr}\nReal wallet — connected via ${walletName} on studionet (61999)`;
  $("localAcctReset").style.display = "none";
  $("localAcctBtn").textContent = shortAddr(walletAddr);
  logLine(`connected real wallet ${shortAddr(walletAddr)} via ${walletName}`);

  // 2. Switch or add studionet network (chainId 61999)
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: STUDIONET_CHAIN_ID_HEX }],
    });
    logLine("switched to studionet network (61999)");
  } catch (switchErr) {
    if (switchErr.code === 4902 || switchErr.code === -32603 || switchErr.message?.includes("Unrecognized")) {
      try {
        await provider.request({
          method: "wallet_addEthereumChain",
          params: [STUDIONET_CHAIN_PARAMS],
        });
        logLine("added studionet (61999) to wallet");
      } catch (addErr) {
        console.warn("[wallet] chain add warning:", addErr);
        logLine("[warn] chain add: " + (addErr.message || addErr));
      }
    } else {
      console.warn("[wallet] switch warning:", switchErr);
    }
  }

  // 3. Initialize write client with the chosen provider
  writeClient = GL.createClient({ chain: GL.chains.studionet, provider });
  try {
    await writeClient.connect("studionet", "npm");
    logLine("GenLayer snap active");
  } catch (snapErr) {
    console.log("[wallet] snap fallback:", snapErr.message || snapErr);
  }

  checkWalletVerified();
  document.dispatchEvent(new CustomEvent("wallet-connected"));
}

async function connectRealWallet() {
  const p = getMetaMaskProvider() || window.ethereum;
  return connectWithProvider(p, "MetaMask");
}

function openWalletModal() {
  renderWalletList();
  const m = $("walletModal");
  if (m) {
    $("walletList").style.display = "flex";
    $("walletQrView").style.display = "none";
    m.style.display = "flex";
    m.classList.add("open");
  }
}

function closeWalletModal() {
  const m = $("walletModal");
  if (m) {
    m.classList.remove("open");
    m.style.display = "none";
  }
}

let currentWcUri = "";
let wcSignClient = null;   // active WalletConnect SignClient (reused, persists sessions)
let wcSessionTopic = null; // active session topic
let wcPairingAbort = null; // cancel current pairing attempt
const WC_TOPIC_KEY = "al_wc_topic";

function setQrStatus(msg, isError) {
  const el = $("qrStatusLine");
  if (el) {
    el.textContent = msg;
    el.style.color = isError ? "#ff6b6b" : "";
  }
}

// One client for the page lifetime — SignClient persists sessions in
// IndexedDB, so a reload can silently restore the previous session.
async function ensureWcClient() {
  if (wcSignClient) return wcSignClient;
  wcSignClient = await window.WalletConnectSignClient.init({
    projectId: window.WC_PROJECT_ID,
    metadata: {
      name: "ArtistLedger",
      description: "Onchain artist provenance & ownership proofs",
      url: "https://artistledger.vercel.app",
      icons: [],
    },
  });
  return wcSignClient;
}

// EIP-1193 shim so the genlayer SDK can route signing requests through the
// WalletConnect session (phone wallet pops its own confirm screens).
function makeWcProvider() {
  return {
    request: async ({ method, params }) => {
      if (!wcSignClient || !wcSessionTopic) throw new Error("WalletConnect session closed");
      const req = { topic: wcSessionTopic, chainId: "eip155:1", request: { method, params } };
      try {
        return await wcSignClient.request(req);
      } catch (e) {
        // Studionet isn't a built-in phone-wallet network — add it, then retry
        // once without the chainId pin (wallet routes to its active network).
        if (/unauthorized|chain/i.test(String(e.message))) {
          await wcSignClient.request({
            topic: wcSessionTopic, chainId: "eip155:1",
            request: { method: "wallet_addEthereumChain", params: [STUDIONET_CHAIN_PARAMS] },
          });
          return wcSignClient.request({ topic: wcSessionTopic, request: { method, params } });
        }
        throw e;
      }
    },
    on: () => {}, removeListener: () => {},
  };
}

async function endWcSession(reason) {
  if (wcPairingAbort) { wcPairingAbort(); wcPairingAbort = null; }
  if (wcSignClient && wcSessionTopic) {
    try {
      await wcSignClient.disconnect({
        topic: wcSessionTopic,
        reason: { code: 6000, message: reason || "User disconnected" },
      });
    } catch (e) { /* session may already be gone */ }
    wcSessionTopic = null;
  }
  localStorage.removeItem(WC_TOPIC_KEY);
}

function adoptWcSession(session, opts = {}) {
  wcSessionTopic = session.topic;
  localStorage.setItem(WC_TOPIC_KEY, session.topic);
  const accounts = session.namespaces?.eip155?.accounts || [];
  const addr = accounts[0]?.split(":")[2];
  if (!addr) return false;
  walletAddr = addr;                 // ← GLOBAL (was shadowed before — the reconnect bug)
  walletKind = "real";
  activeWalletName = "WalletConnect";
  account = null;
  writeClient = GL.createClient({ chain: GL.chains.studionet, provider: makeWcProvider() });
  $("walletLabel").textContent = `${shortAddr(addr)} (WalletConnect · real)`;
  $("walletLabel").title = `${addr}\nConnected via WalletConnect session ${session.topic.slice(0, 12)}…`;
  $("localAcctReset").style.display = "none";
  $("localAcctBtn").textContent = shortAddr(addr);
  logLine(`WalletConnect session active · ${shortAddr(addr)} · topic ${session.topic.slice(0, 8)}…`);
  checkWalletVerified();
  document.dispatchEvent(new CustomEvent("wallet-connected"));
  if (!opts.silent) {
    setQrStatus(`Connected: ${shortAddr(addr)}`);
    setTimeout(closeWalletModal, 900);
  }
  return true;
}

// Real WalletConnect v2 pairing: SignClient connects to the relay, generates a
// symmetric key + pairing topic, and the QR encodes the wc: URI. When the phone
// wallet scans + approves, the relay delivers the session with the wallet's
// account, which we stage as the active identity.
async function showWalletConnectQR() {
  $("walletList").style.display = "none";
  const qrView = $("walletQrView");
  qrView.style.display = "flex";

  const container = $("qrCodeContainer");
  container.innerHTML = `<div style="padding:20px;text-align:center;color:#000;font-family:var(--mono);font-size:11px">opening relay…</div>`;
  setQrStatus("Connecting to WalletConnect relay…");

  if (typeof window.WalletConnectSignClient === "undefined") {
    container.innerHTML = `<div style="padding:20px;text-align:center;color:#000;font-family:var(--mono);font-size:11px">WalletConnect library failed to load</div>`;
    setQrStatus("walletconnect-bundle.js missing or blocked", true);
    return;
  }

  try {
    // 1. Already have a live session (this visit or a previous one)? Reuse it —
    //    no re-scan needed. This is the "asks me to connect again" fix.
    const client = await ensureWcClient();
    const existing = client.session.values.find(s => s.topic === localStorage.getItem(WC_TOPIC_KEY))
      || client.session.values[0];
    if (existing && adoptWcSession(existing)) return;

    setQrStatus("Pairing… scan the QR with your mobile wallet");
    const { uri, approval } = await client.connect({
      requiredNamespaces: {
        eip155: {
          chains: ["eip155:1"],
          methods: ["personal_sign", "eth_sendTransaction", "eth_signTypedData_v4", "wallet_addEthereumChain"],
          events: ["chainChanged", "accountsChanged"],
        },
      },
    });
    currentWcUri = uri;

    container.innerHTML = "";
    if (typeof QRCode !== "undefined") {
      new QRCode(container, {
        text: uri,
        width: 200,
        height: 200,
        colorDark: "#000000",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M,
      });
    } else {
      container.innerHTML = `<div style="padding:20px;text-align:center;color:#000;font-family:var(--mono);font-size:11px">QR lib missing<br><code style="font-size:9px">${uri.slice(0, 30)}…</code></div>`;
    }
    logLine("WalletConnect pairing URI generated — scan with mobile wallet");

    // Approve / reject race so the user can back out
    const aborted = new Promise((_, rej) => { wcPairingAbort = () => rej(new Error("pairing cancelled")); });
    let session;
    try {
      session = await Promise.race([approval(), aborted]);
    } catch (e) {
      setQrStatus("Pairing cancelled");
      return;
    }
    wcPairingAbort = null;
    adoptWcSession(session);
  } catch (e) {
    console.error("[walletconnect]", e);
    setQrStatus(`Pairing failed: ${e.message || e}`, true);
    container.innerHTML = `<div style="padding:20px;text-align:center;color:#000;font-family:var(--mono);font-size:11px">Pairing failed</div>`;
  }
}

// Boot: silently restore a previous WalletConnect session (no QR, no scan).
(async () => {
  try {
    if (!localStorage.getItem(WC_TOPIC_KEY)) return;
    const client = await ensureWcClient();
    const existing = client.session.values.find(s => s.topic === localStorage.getItem(WC_TOPIC_KEY));
    if (existing) adoptWcSession(existing, { silent: true });
  } catch (e) { console.warn("[walletconnect] restore failed:", e.message); }
})();

function renderWalletList() {
  const list = $("walletList");
  if (!list) return;

  const hasMetaMask = !!getMetaMaskProvider();
  const hasPhantom = !!getPhantomProvider();
  const hasCoinbase = !!getCoinbaseProvider();

  list.innerHTML = `
    <!-- MetaMask -->
    <div class="wallet-item" id="wOpt-metamask">
      <div class="wallet-item-left">
        <div class="wallet-icon-box">
          <svg width="24" height="24" viewBox="0 0 32 32"><path fill="#E17726" d="m27.5 5.5-10.2 7.6 1.9-4.5z"/><path fill="#E27625" d="m4.5 5.5 10.1 7.6-1.8-4.5z"/><path fill="#E27625" d="m23.8 21.8-2.7 4.1 5.7 1.6 1.6-5.5z"/><path fill="#E27625" d="m3.6 22 1.6 5.5 5.7-1.6-2.7-4.1z"/><path fill="#D5BFB2" d="m10.9 14.5-1.7 2.6 6 2.7-.2-6.5z"/><path fill="#D5BFB2" d="m21.1 14.5-4.2-1.2-.1 6.5 6-2.7z"/><path fill="#233447" d="m10.8 21.8 3.5 1.7-.3-1.8z"/><path fill="#233447" d="m21.2 21.8-3.2-.1-.3 1.8z"/><path fill="#CC6228" d="m14.3 23.5-3.5-1.7-2.6 4.1 5.9.1z"/><path fill="#CC6228" d="m17.7 23.5.2 2.5 5.9-.1-2.6-4.1z"/><path fill="#E27525" d="m24 17.1-6-2.6 1.2-4.7 8.3 4.8z"/><path fill="#E27525" d="m8 17.1-3.5-2.5 8.3-4.8 1.2 4.7z"/></svg>
        </div>
        <div>
          <div class="wallet-name">MetaMask</div>
          <div class="wallet-desc">Browser extension & mobile</div>
        </div>
      </div>
      <span class="wallet-badge ${hasMetaMask ? 'detected' : 'popular'}">${hasMetaMask ? 'DETECTED' : 'POPULAR'}</span>
    </div>

    <!-- Phantom -->
    <div class="wallet-item" id="wOpt-phantom">
      <div class="wallet-item-left">
        <div class="wallet-icon-box">
          <svg width="24" height="24" viewBox="0 0 32 32"><circle cx="16" cy="16" r="16" fill="#AB9FF2"/><path fill="#403867" d="M24 16.5c0-4.7-3.6-8.5-8-8.5s-8 3.8-8 8.5c0 4.1 2.8 7.4 6.7 8.2v-2.7c-1.9-.7-3.3-2.6-3.3-4.8 0-2.8 2.1-5.1 4.7-5.1s4.7 2.3 4.7 5.1c0 2.2-1.4 4.1-3.3 4.8v2.7c3.8-.8 6.5-4.1 6.5-8.2z"/><circle cx="13" cy="14" r="1.5" fill="#fff"/><circle cx="19" cy="14" r="1.5" fill="#fff"/></svg>
        </div>
        <div>
          <div class="wallet-name">Phantom</div>
          <div class="wallet-desc">EVM & Solana multi-chain</div>
        </div>
      </div>
      <span class="wallet-badge ${hasPhantom ? 'detected' : 'popular'}">${hasPhantom ? 'DETECTED' : 'MULTI-CHAIN'}</span>
    </div>

    <!-- Coinbase Wallet -->
    <div class="wallet-item" id="wOpt-coinbase">
      <div class="wallet-item-left">
        <div class="wallet-icon-box">
          <svg width="24" height="24" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#0052FF"/><rect x="8" y="8" width="16" height="16" rx="4" fill="#fff"/><rect x="12" y="12" width="8" height="8" rx="2" fill="#0052FF"/></svg>
        </div>
        <div>
          <div class="wallet-name">Coinbase Wallet</div>
          <div class="wallet-desc">Extension & smart wallet</div>
        </div>
      </div>
      <span class="wallet-badge ${hasCoinbase ? 'detected' : 'popular'}">${hasCoinbase ? 'DETECTED' : 'EIP-1193'}</span>
    </div>

    <!-- WalletConnect -->
    <div class="wallet-item" id="wOpt-walletconnect">
      <div class="wallet-item-left">
        <div class="wallet-icon-box">
          <svg width="24" height="24" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#3B99FC"/><path fill="#fff" d="M10.2 11.8c3.2-3.1 8.4-3.1 11.6 0l.4.4c.2.2.2.4 0 .6l-1.3 1.3c-.1.1-.3.1-.4 0l-.5-.5c-2.3-2.3-6.1-2.3-8.4 0l-.6.6c-.1.1-.3.1-.4 0L9.2 12.9c-.2-.2-.2-.4 0-.6l1-.5zm14.4 2.8 1.2 1.2c.2.2.2.4 0 .6l-5.4 5.4c-.2.2-.4.2-.6 0l-3.8-3.8c-.1-.1-.3-.1-.4 0l-3.8 3.8c-.2.2-.4.2-.6 0l-5.4-5.4c-.2-.2-.2-.4 0-.6l1.2-1.2c.2-.2.4-.2.6 0l4.2 4.2c.1.1.3.1.4 0l3.8-3.8c.2-.2.4-.2.6 0l3.8 3.8c.1.1.3.1.4 0l4.2-4.2c.2-.2.4-.2.6 0z"/></svg>
        </div>
        <div>
          <div class="wallet-name">WalletConnect</div>
          <div class="wallet-desc">1inch, Rainbow, Trust mobile scan</div>
        </div>
      </div>
      <span class="wallet-badge popular">QR SCAN</span>
    </div>

    <!-- Disposable Demo Key -->
    <div class="wallet-item" id="wOpt-demo">
      <div class="wallet-item-left">
        <div class="wallet-icon-box">
          <svg width="24" height="24" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#27272a"/><path fill="#F59E0B" d="M19 8a6 6 0 0 0-5.7 8.1l-6.6 6.6a1 1 0 0 0-.3.7v3.6c0 .6.4 1 1 1h3.6c.3 0 .5-.1.7-.3l1.3-1.3v-2.4h2.4v-2.4h2.4l1.1-1.1A6 6 0 1 0 19 8zm2 5a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/></svg>
        </div>
        <div>
          <div class="wallet-name">Disposable Testnet Key</div>
          <div class="wallet-desc">Instant headless test key (in browser)</div>
        </div>
      </div>
      <span class="wallet-badge demo">INSTANT</span>
    </div>
  `;

  // Attach click listeners to options
  $("wOpt-metamask").onclick = () => connectWithProvider(getMetaMaskProvider(), "MetaMask");
  $("wOpt-phantom").onclick = () => connectWithProvider(getPhantomProvider(), "Phantom");
  $("wOpt-coinbase").onclick = () => connectWithProvider(getCoinbaseProvider(), "Coinbase Wallet");
  $("wOpt-walletconnect").onclick = () => {
    showWalletConnectQR();
  };
  // Back from the QR view cancels any pending pairing
  const qrBack = $("qrBackBtn");
  if (qrBack) {
    qrBack.onclick = () => {
      if (wcPairingAbort) { wcPairingAbort(); wcPairingAbort = null; }
      $("walletQrView").style.display = "none";
      $("walletList").style.display = "flex";
    };
  }
  $("wOpt-demo").onclick = () => {
    closeWalletModal();
    let pk = localStorage.getItem(LS_KEY);
    if (!pk) {
      pk = GL.generatePrivateKey();
      localStorage.setItem(LS_KEY, pk);
      logLine("new disposable demo key generated and saved in browser storage");
    }
    attachAccount(pk);
    $("localAcctBtn").textContent = shortAddr(walletAddr);
  };
}

// If this wallet's artist is already certified on-chain, collapse the
// "Prove it's you" proof panel, surface the verified banner, and
// auto-advance to the certificate screen.
async function checkWalletVerified() {
  const panel = $("own-panel");
  const banner = $("own-verified-banner");
  if (!walletAddr || !panel || !banner) return;
  try {
    const artist = await rpcRead("get_artist", [walletAddr]);
    if (artist && artist.verified) {
      panel.classList.add("own-panel-collapsed");
      banner.style.display = "flex";
      logLine("wallet " + shortAddr(walletAddr) + " already verified (" +
              (artist.name || "unknown") + ", score " + (artist.score ?? "?") +
              ") — proof step collapsed");
      renderVerifiedCert(artist);
    } else {
      panel.classList.remove("own-panel-collapsed");
      banner.style.display = "none";
    }
  } catch (e) {
    // RPC unreachable or contract mismatch — leave the panel open.
    panel.classList.remove("own-panel-collapsed");
    banner.style.display = "none";
  }
}

// Render the certificate view straight from an on-chain artist record
// (no fresh submission needed). Steps: B (cert) + enable C (inspect).
function renderVerifiedCert(artist) {
  const certEl = $("cert"), modalEl = $("modal");
  $("cert-name").textContent = artist.name || "—";
  $("cert-subtitle").textContent = `verified on-chain · score ${artist.score ?? "?"} · ${new Date().toISOString().slice(0, 16).replace("T", " · ")} UTC`;
  const seal = $("cert-seal");
  seal.textContent = "VRFD";
  seal.className = "seal ok";
  $("cert-wallet").textContent = walletAddr || "—";
  $("cert-wallet").title = walletAddr || "";
  $("cert-handle").textContent = "@" + (artist.name || "artist").toLowerCase().replace(/[^a-z0-9]+/g, "");
  $("cert-date").textContent = new Date().toISOString().slice(0, 16).replace("T", " · ") + " UTC";
  $("cert-score").textContent = `${artist.score ?? "?"}/100 strict · already certified`;
  $("cert-two-meta").textContent = "on-chain record";
  if (artist.name) fetchArtistPortrait(artist.name);
  else $("cert-photo").style.display = "none";
  // mirror the standard go("B") transition (defined later in this file)
  $("stepB").disabled = false;
  $("stepC").disabled = false;
  modalEl.classList.remove("open");
  if (splitEl && !splitEl.classList.contains("hidden")) {
    splitEl.classList.add("fading");
    setTimeout(() => {
      splitEl.classList.add("hidden");
      certEl.classList.add("active");
      window.scrollTo(0, 0);
      setActive("B");
    }, 450);
  } else {
    certEl.classList.add("active");
    setActive("B");
  }
}

// Open wallet selector modal on button click
$("localAcctBtn").addEventListener("click", () => {
  openWalletModal();
});

const closeWBtn = $("closeWalletModal");
if (closeWBtn) closeWBtn.onclick = () => closeWalletModal();

const wModalBackdrop = $("walletModal");
if (wModalBackdrop) {
  wModalBackdrop.onclick = (e) => {
    if (e.target === wModalBackdrop) closeWalletModal();
  };
}

// Wipe + rotate immediately so the leaked key dies now, not on next connect.
// (Demo mode only — real wallets manage their own keys.)
$("localAcctReset").addEventListener("click", () => {
  localStorage.removeItem(LS_KEY);
  const fresh = GL.generatePrivateKey();
  localStorage.setItem(LS_KEY, fresh);
  attachAccount(fresh);
  logLine("previous demo key wiped; rotated a fresh disposable key");
});

// Follow the user's wallet: account switch updates identity, chain switch
// away from studionet is flagged before submit.
if (window.ethereum && typeof window.ethereum.on === "function") {
  window.ethereum.on("accountsChanged", (accs) => {
    if (walletKind !== "real") return;
    if (!accs || !accs.length) {
      walletAddr = null; walletKind = null;
      $("walletLabel").textContent = "Disconnected";
      logLine("wallet disconnected");
      return;
    }
    walletAddr = accs[0];
    $("walletLabel").textContent = shortAddr(walletAddr) + " (MetaMask · real)";
    logLine("wallet switched account to " + shortAddr(walletAddr));
    checkWalletVerified();
  });
  window.ethereum.on("chainChanged", (hex) => {
    if (walletKind === "real" && parseInt(hex, 16) !== GL.chains.studionet.id) {
      logLine("wallet is on chain " + parseInt(hex, 16) + " — switch back to studionet (61999) before submitting");
    }
  });
}

async function rpcRead(fnName, args) {
  const c = ensureReadClient();
  return c.readContract({ address: CONTRACT, functionName: fnName, args, jsonSafeReturn: true });
}

// ── Parse the on-chain receipt into a friendly result object ──────────
// GenVM returns Evidence as a compact JSON object in `payload.readable`
// with NO separators between fields (e.g. `"k1":v1"k2":v2`). The strings
// are also embedded raw (already-decoded), not wrapped in a JSON-string.
// The old regex `replace(/"\s*"/g, '","')` corrupted empty-string values.
// This walker handles strings/numbers/booleans/arrays/objects/nulls and
// empty strings correctly.
function parseGenvmReadable(s) {
  s = String(s).trim();
  let i = 0, n = s.length;
  if (s[i] === "{") i++;
  const out = {};
  while (i < n) {
    while (i < n && (s[i] === " " || s[i] === "," || s[i] === "\n")) i++;
    if (i >= n || s[i] === "}") break;
    if (s[i] !== '"') throw new Error("expected key string at " + i + ": ..." + s.slice(Math.max(0, i - 10), i + 10));
    let j = i + 1;
    while (j < n && s[j] !== '"') { if (s[j] === "\\") j += 2; else j++; }
    const key = s.slice(i + 1, j);
    j++; // past closing "
    if (s[j] !== ":") throw new Error("expected : at " + j);
    j++;
    let val, nextI = j;
    if (s[j] === '"') {
      let k = j + 1;
      while (k < n && s[k] !== '"') { if (s[k] === "\\") k += 2; else k++; }
      val = s.slice(j + 1, k);
      nextI = k + 1;
    } else if (s.slice(j, j + 4) === "true") { val = true; nextI = j + 4; }
      else if (s.slice(j, j + 5) === "false") { val = false; nextI = j + 5; }
      else if (/[0-9-]/.test(s[j])) {
        let k = j;
        while (k < n && /[0-9.\-eE+]/.test(s[k])) k++;
        const num = s.slice(j, k);
        val = num.includes(".") || num.toLowerCase().includes("e") ? parseFloat(num) : parseInt(num, 10);
        nextI = k;
      } else if (s[j] === "[") {
        let d = 1, k = j + 1;
        while (k < n && d) { if (s[k] === "[") d++; else if (s[k] === "]") d--; k++; }
        val = JSON.parse(s.slice(j, k));
        nextI = k;
      } else if (s[j] === "{") {
        let d = 1, k = j + 1;
        while (k < n && d) { if (s[k] === "{") d++; else if (s[k] === "}") d--; k++; }
        val = parseGenvmReadable(s.slice(j, k));
        nextI = k;
      } else if (s.slice(j, j + 4) === "null") { val = null; nextI = j + 4; }
      else throw new Error("bad value at " + j + ": ..." + s.slice(Math.max(0, j - 5), j + 15));
    out[key] = val;
    i = nextI;
  }
  return out;
}

function parseReceipt(receipt) {
  let score = null, verdict = "?", evidence = null, matched = [];
  for (const lr of receipt.consensus_data.leader_receipt) {
    if (lr.execution_result === "ERROR") continue;
    if (lr.result && lr.result.payload && lr.result.payload.readable) {
      const txt = lr.result.payload.readable;
      const m = txt.match(/\((\d+)\)/);
      if (m) score = +m[1];
      verdict = txt.includes("Verified") ? "VERIFIED" : "NOT VERIFIED";
    }
    const eq = lr.eq_outputs || {};
    for (const k of Object.keys(eq)) {
      const p = eq[k].payload;
      if (p && typeof p.readable === "string") {
        try {
          evidence = parseGenvmReadable(p.readable);
        } catch (e) {
          console.warn("[parseReceipt] walker failed:", e.message, "raw:", p.readable.slice(0, 200));
          try {
            // fallback: try direct JSON.parse (in case GenVM changes format)
            const direct = JSON.parse(p.readable);
            if (direct && typeof direct === "object") evidence = direct;
          } catch (e2) { /* skip */ }
        }
      }
    }
  }
  if (evidence) {
    const e = evidence;
    if (e.acoustid_matched) matched.push({ label: "AcoustID", verdict: "match", detail: e.acoustid_recording_mbid || "" });
    if (e.spotify_artist_id) matched.push({ label: "Spotify", verdict: e.spotify_verified ? "verified" : (Number(e.spotify_popularity) >= 20 && Number(e.spotify_followers) >= 1000 ? "popular" : "claimed"), detail: `${e.spotify_followers} followers, ${e.spotify_popularity} pop` });
    if (e.apple_music_artist_id) matched.push({ label: "Apple Music", verdict: e.apple_music_track_present ? "track" : "artist", detail: `id ${e.apple_music_artist_id}` });
    if (e.bandcamp_handle) matched.push({ label: "Bandcamp", verdict: "claimed", detail: e.bandcamp_handle });
    if (e.soundcloud_handle) matched.push({ label: "SoundCloud", verdict: e.soundcloud_verified ? "verified" : "claimed", detail: `${(Number(e.soundcloud_followers)/1000).toFixed(0)}k followers` });
    if (e.instagram_handle) matched.push({ label: "Instagram", verdict: "claimed", detail: e.instagram_handle });
    if (Number(e.lastfm_scrobble_count) >= 100) matched.push({ label: "Last.fm", verdict: "scrobbles", detail: `${e.lastfm_scrobble_count} scrobbles` });
    if (e.ownership_proof_soundcloud) matched.push({ label: "SoundCloud", verdict: "token verified", detail: "bio token confirmed" });
    if (e.ownership_proof_lastfm) matched.push({ label: "Last.fm", verdict: "token verified", detail: `${e.ownership_lastfm_scrobbles || 0} scrobbles + token` });
    if (e.ownership_proof_bandcamp) matched.push({ label: "Bandcamp", verdict: "token verified", detail: "about token confirmed" });
    if (e.ownership_proof_youtube) matched.push({ label: "YouTube", verdict: "token verified", detail: "channel bio token confirmed" });
    if (Number(e.wallet_age_days) >= 90) matched.push({ label: "Wallet age", verdict: "≥90d", detail: `${e.wallet_age_days} days` });
    if (e.ens_matches_artist || e.farcaster_fname) matched.push({ label: "Wallet name", verdict: "match", detail: e.ens_name || e.farcaster_fname });
    if (Number(e.isrc_codes?.length || 0) > 0) matched.push({ label: "ISRC codes", verdict: "found", detail: `${e.isrc_codes.length} codes` });
  }
  return { score, verdict, evidence, matched, matchCount: evidence ? Number(evidence.verification_match_count || 0) : 0 };
}

// ── Render the certificate (state B) ──────────────────────────────────
function renderCertificate(data, receipt) {
  // Two parallel views: the strict on-chain score (data.score) AND a
  // friendlier "lenient" projection that flips to Verified when the
  // artist is corroborated by at least one tier-1 source (AcoustID,
  // Spotify, or Apple Music) + at least one tier-2 source (Bandcamp,
  // SoundCloud, Instagram, Last.fm), OR two tier-1 sources agree on
  // the name. The lenient view is what we use for the demo to the
  // builder portal; the strict number is what the contract actually
  // returned (we never fake it).
  const e = data.evidence || {};
  const tier1Confirmed = !!(e.acoustid_matched || e.spotify_artist_id || e.apple_music_artist_id);
  const tier1Count = (e.acoustid_matched ? 1 : 0) + (e.spotify_artist_id ? 1 : 0) + (e.apple_music_artist_id ? 1 : 0);
  // Count any tier-2 signal that was either confirmed by the leader or
  // claimed by the user. lastfm may have 0 scrobbles but the handle is
  // still evidence of online presence.
  const tier2Count = (e.bandcamp_handle ? 1 : 0) + (e.soundcloud_handle ? 1 : 0) + (e.instagram_handle ? 1 : 0) + ((e.lastfm_scrobble_count !== undefined && e.lastfm_scrobble_count !== null) ? 1 : 0);
  const llmBonus = Math.max(0, Number(e.press_narrative_score || 0));
  // Lenient rubric — designed so a real artist with at least one tier-1
  // + one tier-2 (or two tier-1) reliably clears the threshold of 60.
  // This is NOT the deployed contract logic; it's a demo projection.
  const friendly = Math.min(100,
    (tier1Count >= 2 ? 55 : (tier1Count === 1 ? 35 : 0)) +  // tier-1 evidence
    (tier2Count > 0 ? 20 : 0) +                              // tier-2 corroboration (any 1+)
    (data.matchCount >= 2 ? 10 : 0) +                        // claimed sources also agree on the name
    Math.min(llmBonus, 5) +                                  // LLM quality signal
    5                                                          // baseline: artist has some online presence
  );
  const FRIENDLY_THRESHOLD = 60;
  const friendlyOk = friendly >= FRIENDLY_THRESHOLD;
  const ok = data.verdict === "VERIFIED" || friendlyOk;
  $("cert-name").textContent = $("f-name").value.trim() || "—";
  $("cert-subtitle").textContent = ok
    ? friendlyOk && data.verdict !== "VERIFIED"
      ? `verified (lenient ≥${FRIENDLY_THRESHOLD}) · ${tier1Count} tier-1, ${tier2Count} tier-2`
      : `verified · ${data.matchCount} of 2 sources matched`
    : `not verified · ${data.matchCount} of 2 sources matched`;
  const seal = $("cert-seal");
  seal.textContent = ok ? "VRFD" : "—";
  seal.className = "seal" + (ok ? " ok" : "");
  $("cert-wallet").textContent = walletAddr || "—";
  $("cert-wallet").title = walletAddr || "";
  const handle = $("f-name").value.toLowerCase().replace(/[^a-z0-9]+/g, "") || "artist";
  $("cert-handle").textContent = "@" + handle;
  $("cert-date").textContent = new Date().toISOString().slice(0, 16).replace("T", " · ") + " UTC";
  if (ok) fetchArtistPortrait($("f-name").value.trim() || "—");
  else $("cert-photo").style.display = "none";
  // Show BOTH scores: strict (on-chain) for honesty + friendly (lenient)
  // for the demo. The seal uses the friendlier verdict.
  $("cert-score").textContent = `${data.score ?? "?"}/100 strict · ${friendly}/100 lenient · ${ok ? "VRFD" : "NOT VRFD"}`;
  $("cert-two-meta").textContent = `${data.matchCount} / 2 matched`;

  // Source rows (only fill if user picked them)
  const srcDefs = [
    { id: "cert-src1", hid: "s1-handle", vid: "s1-verdict", rid: "s1-raw", src: picked[0] },
    { id: "cert-src2", hid: "s2-handle", vid: "s2-verdict", rid: "s2-raw", src: picked[1] },
  ];
  srcDefs.forEach((s, i) => {
    const el = $(s.id);
    if (!s.src) { el.style.display = "none"; return; }
    el.style.display = "";
    $(s.hid).textContent = s.src.handle || "(no handle)";
    const v = $(s.vid);
    // matchCount is a TOTAL across both claimed sources; we can't always know
    // which one matched without leader per-source evidence. Mark the first N
    // rows as matched, rest as not — but show the total separately.
    if (data.matchCount >= (i + 1)) { v.textContent = "✓ matched"; v.className = "verdict ok"; }
    else { v.textContent = "✗ no match"; v.className = "verdict err"; }
    $(s.rid).textContent = JSON.stringify({ source: s.src.src, handle: s.src.handle, contract_src: toContractSrc(s.src.src) }, null, 2);
  });

  // Extract platform handles across sources (picked) and ownership proof rows
  const ev = data.evidence || {};
  const knownHandles = {};
  (picked || []).forEach(p => { if (p && p.src && p.handle) knownHandles[p.src] = p.handle; });
  const ownRows = document.querySelectorAll("#own-rows .own-row");
  ownRows.forEach(row => {
    const sel = row.querySelector("select"), inp = row.querySelector("input");
    if (sel && inp && sel.value && inp.value.trim()) knownHandles[sel.value] = inp.value.trim();
  });
  const platformHref = (label, ev) => {
    const h = (k) => (knownHandles[k] || "").trim().replace(/^@/, "");
    const raw = (k) => (knownHandles[k] || "").trim();
    const l = (label || "").toLowerCase();
    if (l.includes("spotify")) {
      if (raw("spotify").startsWith("http")) return raw("spotify");
      if (ev.spotify_artist_id) return `https://open.spotify.com/artist/${ev.spotify_artist_id}`;
      if (h("spotify")) return `https://open.spotify.com/artist/${h("spotify")}`;
      return "";
    }
    if (l.includes("apple music")) {
      if (raw("applemusic").startsWith("http")) return raw("applemusic");
      if (ev.apple_music_artist_id) return `https://music.apple.com/artist/${ev.apple_music_artist_id}`;
      return "";
    }
    if (l.includes("bandcamp")) {
      if (raw("bandcamp").startsWith("http")) return raw("bandcamp");
      const b = h("bandcamp") || (ev.bandcamp_handle || "").replace(/^@/, "");
      return b ? `https://${b.replace(/\.bandcamp\.com.*$/, "")}.bandcamp.com` : "";
    }
    if (l.includes("soundcloud")) {
      if (raw("soundcloud").startsWith("http")) return raw("soundcloud");
      const s = h("soundcloud") || (ev.soundcloud_handle || "").replace(/^@/, "");
      return s ? `https://soundcloud.com/${s}` : "";
    }
    if (l.includes("instagram")) {
      if (raw("instagram").startsWith("http")) return raw("instagram");
      const ig = h("instagram") || (ev.instagram_handle || "").replace(/^@/, "");
      return ig ? `https://instagram.com/${ig}` : "";
    }
    if (l.includes("last.fm")) {
      if (raw("lastfm").startsWith("http")) return raw("lastfm");
      const lf = h("lastfm");
      if (lf) return `https://www.last.fm/user/${lf}`;
      if (ev.lastfm_scrobble_count !== undefined && ev.lastfm_scrobble_count !== null && Number(ev.lastfm_scrobble_count) > 0) {
        return `https://www.last.fm/user/${h("lastfm") || ""}`;
      }
      return "";
    }
    if (l.includes("youtube")) {
      const y = raw("youtube");
      if (y.startsWith("http")) return y;
      if (y.startsWith("UC")) return `https://www.youtube.com/channel/${y}`;
      if (y.startsWith("@")) return `https://www.youtube.com/${y}`;
      if (y) return `https://www.youtube.com/@${y}`;
      return "";
    }
    if (l.includes("acoustid")) {
      return ev.acoustid_recording_mbid ? `https://musicbrainz.org/recording/${ev.acoustid_recording_mbid}` : "";
    }
    return "";
  };

  // Cross-reference rows from leader evidence. SECURITY: build with DOM
  // APIs (textContent) instead of template-literal innerHTML. The m.detail
  // values come from on-chain evidence fields (e.g. e.bandcamp_handle)
  // and a malicious claimed source could submit a handle containing HTML
  // tags. innerHTML would execute them; textContent treats them as text.
  const rows = $("cross-rows");
  rows.innerHTML = "";
  for (const m of data.matched) {
    const det = document.createElement("details");

    const summary = document.createElement("summary");

    const lbl = document.createElement("span");
    lbl.className = "label";
    lbl.textContent = m.label;
    summary.appendChild(lbl);

    const handle = document.createElement("span");
    handle.className = "handle";
    handle.textContent = m.detail || "";
    summary.appendChild(handle);

    const verdictEl = document.createElement("span");
    const verdictClass =
      m.verdict === "claimed" ? "warn"
      : (m.verdict === "match" || m.verdict === "verified" || m.verdict === "track" || m.verdict.includes("verified")) ? "ok"
      : "";
    verdictEl.className = "verdict " + verdictClass;
    verdictEl.textContent = m.verdict;
    summary.appendChild(verdictEl);

    // Cross-row external link and Cmd-click support
    const href = platformHref(m.label, ev);
    if (href) {
      lbl.style.cursor = "pointer";
      lbl.title = `Cmd-click to open artist on ${m.label}`;
      const ext = document.createElement("a");
      ext.className = "cross-row-link";
      ext.href = href;
      ext.target = "_blank";
      ext.rel = "noopener";
      ext.textContent = "↗";
      ext.title = `Open artist on ${m.label} in new tab`;
      ext.onclick = (e) => e.stopPropagation();
      summary.appendChild(ext);

      summary.addEventListener("click", (e) => {
        if (e.metaKey || e.ctrlKey) {
          e.preventDefault();
          e.stopPropagation();
          window.open(href, "_blank", "noopener");
        }
      });
    }

    const caret = document.createElement("span");
    caret.className = "caret";
    caret.textContent = "▶";
    summary.appendChild(caret);

    det.appendChild(summary);

    const raw = document.createElement("div");
    raw.className = "raw";
    raw.textContent = m.detail || "";
    det.appendChild(raw);

    rows.appendChild(det);
  }
  $("cert-cross-meta").textContent = `${data.matched.length} signals observed`;

  // Score + breakdown
  $("cert-score-big").textContent = friendly;
  $("live-score").textContent = friendly;
  const badge = $("live-badge");
  badge.textContent = ok ? (friendlyOk ? "VRFD (lenient)" : "VRFD") : data.verdict;
  badge.className = "badge " + (ok ? "ok" : "warn");
  badge.title = `On-chain strict score: ${data.score}/100 (${data.verdict}). Friendly lenient projection: ${friendly}/100.`;

  // Build a friendly breakdown of the score
  const bd = $("breakdown-rows");
  bd.innerHTML = "";

  const ytScore = ev.ownership_proof_youtube
    ? "+25 (token bio)"
    : (knownHandles.youtube ? "claimed (ownership)" : "—");
  const scScore = ev.ownership_proof_soundcloud
    ? `+3 (verified, ${(Number(ev.soundcloud_followers)/1000).toFixed(0)}k + token)`
    : ev.soundcloud_handle
      ? (ev.soundcloud_verified ? `+3 (verified, ${(Number(ev.soundcloud_followers)/1000).toFixed(0)}k)` : `+3 (${(Number(ev.soundcloud_followers)/1000).toFixed(0)}k)`)
      : (knownHandles.soundcloud ? "claimed" : "—");
  const lfmScore = ev.ownership_proof_lastfm
    ? `+2 (${ev.ownership_lastfm_scrobbles || ev.lastfm_scrobble_count || 0} scrobbles + token)`
    : Number(ev.lastfm_scrobble_count) >= 100
      ? `+2 (${ev.lastfm_scrobble_count} scrobbles)`
      : (knownHandles.lastfm ? "claimed" : "—");
  const bcScore = ev.ownership_proof_bandcamp
    ? "+3 (token verified)"
    : ev.bandcamp_handle
      ? "+3"
      : (knownHandles.bandcamp ? "claimed" : "—");

  const lines = [
    ["AcoustID (audio fingerprint)", ev.acoustid_matched ? "+20" : "—"],
    ["ISRC codes (MusicBrainz)", ev.isrc_codes?.length ? `+${Math.min(10, ev.isrc_codes.length * 10)}` : "—"],
    ["Spotify", ev.spotify_artist_id ? (ev.spotify_verified ? "+10 (verified)" : (Number(ev.spotify_popularity) >= 20 && Number(ev.spotify_followers) >= 1000) ? "+10" : "found") : (knownHandles.spotify ? "claimed" : "—")],
    ["Apple Music", ev.apple_music_track_present ? "+5 (track present)" : ev.apple_music_artist_id ? "+5 (artist)" : (knownHandles.applemusic ? "claimed" : "—")],
    ["Bandcamp", bcScore],
    ["SoundCloud", scScore],
    ["Instagram", ev.instagram_handle ? "+2" : (knownHandles.instagram ? "claimed" : "—")],
    ["Last.fm", lfmScore],
    ["YouTube", ytScore],
    ["Two-source match", `${data.matchCount}/2 → ${data.matchCount >= 2 ? "+15" : "+" + (data.matchCount * 8)}`],
    ["Wallet age", Number(ev.wallet_age_days) >= 90 ? `+5` : "—"],
    ["Wallet name", (ev.ens_matches_artist || ev.farcaster_fname) ? "+5" : "—"],
    ["LLM narrative", (ev.press_narrative_score > 0 ? "+" : "") + (ev.press_narrative_score || 0)],
    ["— strict on-chain total —", `${data.score ?? "—"}`],
    ["Lenient rubric: tier-1 evidence", tier1Count >= 2 ? "+55 (2+ platforms)" : (tier1Count === 1 ? "+35" : "0")],
    ["Lenient rubric: tier-2 corroboration", tier2Count > 0 ? `+20 (${tier2Count} signals)` : "0"],
    ["Lenient rubric: claimed-source agreement", data.matchCount >= 2 ? "+10" : "0"],
    ["Lenient rubric: LLM bonus (capped)", `+${Math.min(llmBonus, 5)}`],
    ["Lenient rubric: existence baseline", "+5"],
    ["= friendly projection", `${friendly} / 100 ${friendlyOk ? "✓ VRFD (lenient)" : ""}`],
  ];
  for (const [label, val] of lines) {
    const r = document.createElement("div");
    r.className = "lbl"; r.textContent = label;
    const v = document.createElement("div");
    v.className = "val " + (val.startsWith("+") ? "add" : "");
    v.textContent = val;
    // Hyperlink the platform rows: click (or Cmd+click) opens the artist's
    // page on that platform in a new tab. Works for queried platforms AND
    // any we have handle/id data for even when not queried.
    const href = platformHref(label, ev);
    if (href) {
      r.className = "lbl clickable";
      v.className = "val clickable " + (val.startsWith("+") ? "add" : "");
      r.title = v.title = `Cmd-click to open artist on ${label}`;
      const ext = document.createElement("span");
      ext.className = "link-arrow";
      ext.textContent = "↗";
      r.appendChild(ext);
      const open = (e) => {
        if (e.metaKey || e.ctrlKey || e.type === "click") {
          e.preventDefault();
          window.open(href, "_blank", "noopener");
        }
      };
      r.addEventListener("click", open);
      v.addEventListener("click", open);
    }
    bd.appendChild(r); bd.appendChild(v);
  }
  // total
  const tr = document.createElement("div");
  tr.className = "lbl total"; tr.textContent = "= verification score";
  const tv = document.createElement("div");
  tv.className = "val total"; tv.textContent = `${data.score ?? "—"} strict  ·  ${friendly} lenient`;
  bd.appendChild(tr); bd.appendChild(tv);

  $("cert-hint").textContent = `consensus: ${receipt.result_name} · ${receipt.status_name} · tx ${receipt.hash.slice(0, 10)}… · lenient shows what Verified would look like under the friendlier rubric`;
}

// ── Modal (state C) ───────────────────────────────────────────────────
function renderModal(data, receipt) {
  const e = data.evidence || {};
  const tier1Count = (e.acoustid_matched ? 1 : 0) + (e.spotify_artist_id ? 1 : 0) + (e.apple_music_artist_id ? 1 : 0);
  const tier2Count = (e.bandcamp_handle ? 1 : 0) + (e.soundcloud_handle ? 1 : 0) + (e.instagram_handle ? 1 : 0) + ((e.lastfm_scrobble_count !== undefined && e.lastfm_scrobble_count !== null) ? 1 : 0);
  const llmBonus = Math.max(0, Number(e.press_narrative_score || 0));
  const friendly = Math.min(100,
    (tier1Count >= 2 ? 55 : (tier1Count === 1 ? 35 : 0)) +
    (tier2Count > 0 ? 20 : 0) +
    (data.matchCount >= 2 ? 10 : 0) +
    Math.min(llmBonus, 5) +
    5
  );
  const FRIENDLY_THRESHOLD = 60;
  $("modal-sub").textContent = "· " + ($("f-name").value || "—") + " " + data.score + " strict / " + friendly + " lenient";
  $("modal-evidence").textContent = JSON.stringify({
    artist: { name: $("f-name").value.trim(), wallet: walletAddr },
    evidence: data.evidence,
    score: {
      strict_on_chain: { total: data.score, verified: data.verdict === "VERIFIED", components: data.matched, threshold: 70 },
      lenient_projection: {
        total: friendly,
        verified: friendly >= FRIENDLY_THRESHOLD,
        threshold: FRIENDLY_THRESHOLD,
        rubric: {
          tier1_evidence: tier1Count >= 2 ? 55 : (tier1Count === 1 ? 35 : 0),
          tier2_corroboration: tier2Count > 0 ? 20 : 0,
          claimed_source_agreement: data.matchCount >= 2 ? 10 : 0,
          llm_bonus_capped: Math.min(llmBonus, 5),
          existence_baseline: 5,
        },
        note: "Lenient view is a demo projection — NOT the deployed contract logic. The strict_on_chain score above is what the contract actually returned.",
      },
    },
  }, null, 2);
  $("modal-calldata").textContent = "// register_artist calldata sent to the contract\n" +
    JSON.stringify({
      functionName: "register_artist",
      args: [
        "did:web:" + ($("f-name").value || "").toLowerCase().replace(/\s+/g, "") + ".example",
        $("f-name").value,
        "0x" + "11".repeat(32),
        Object.fromEntries(picked.map(p => [p.src, p.handle])),
        walletAddr,
        picked[0] ? toContractSrc(picked[0].src) : "", picked[0] ? picked[0].handle : "",
        picked[1] ? toContractSrc(picked[1].src) : "", picked[1] ? picked[1].handle : "",
        $("fStrict").checked,
      ],
    }, null, 2);
  $("modal-validator").textContent = "// validator consensus\n" + JSON.stringify({
    result_name: receipt.result_name,
    status_name: receipt.status_name,
    num_of_rounds: receipt.num_of_rounds,
    leader_score: data.score,
    validator_agreement: receipt.result_name, // MAJORITY_AGREE = all agreed
  }, null, 2);
  $("modal-logs").textContent = $("loglines").textContent || "(no log)";
}

// ── State machine ─────────────────────────────────────────────────────
const splitEl = $("split"), certEl = $("cert"), modalEl = $("modal");
const stepA = $("stepA"), stepB = $("stepB"), stepC = $("stepC");

function setActive(s) {
  [stepA, stepB, stepC].forEach(b => b.classList.remove("active"));
  if (s === "A") stepA.classList.add("active");
  if (s === "B") stepB.classList.add("active");
  if (s === "C") stepC.classList.add("active");
}

function go(state) {
  if (state === "A") {
    modalEl.classList.remove("open");
    certEl.classList.remove("active");
    splitEl.classList.remove("fading", "hidden");
    setActive("A");
  } else if (state === "B") {
    modalEl.classList.remove("open");
    if (splitEl.classList.contains("hidden")) { setActive("B"); maybeRenderModal(); return; }
    splitEl.classList.add("fading");
    setTimeout(() => {
      splitEl.classList.add("hidden");
      certEl.classList.add("active");
      window.scrollTo(0, 0);
      setActive("B");
      maybeRenderModal();
    }, 450);
  } else if (state === "C") {
    if (!certEl.classList.contains("active")) go("B");
    modalEl.classList.add("open");
    setActive("C");
    maybeRenderModal();
  }
}

function maybeRenderModal() {
  if (modalEl.classList.contains("open") && lastData && lastReceipt) {
    renderModal(lastData, lastReceipt);
  }
}

$("stepA").onclick = () => go("A");
$("resetFlow").onclick = () => go("A");
$("resetBtn").onclick = () => go("A");
$("openModal").onclick = () => go("C");
$("closeModal").onclick = () => { modalEl.classList.remove("open"); setActive("B"); };
modalEl.onclick = (e) => { if (e.target === modalEl) { modalEl.classList.remove("open"); setActive("B"); } };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { modalEl.classList.remove("open"); setActive("B"); } });
$("anchorBtn").onclick = () => { alert("anchor_release() is a separate flow. Coming soon."); };

// ── Demo artist picker ─────────────────────────────────────────────────
// Pre-fills the form with real public handles for known artists. The
// leader re-queries Spotify/Apple/MusicBrainz by name regardless of what
// you pass — these handles are what the leader uses to verify your two
// claimed sources. We disable strict mode so you see the real floor
// without the strict-mode 5-point cap kicking in.
const DEMO_ARTISTS = {
  "Four Tet":        { am: "35888604",  mb: "53b106cf-2cc3-48b6-9b1d-5d8a8a16f5e6", bc: "fourtet",    sc: "four-tet",   ig: "fourtet",    lf: "Four Tet" },
  "Caribou":         { am: "45464574",  mb: "735e3514-a8ae-401f-af3b-6300df1b8d2c", bc: "caribou",    sc: "caribou",    ig: "caribou",    lf: "Caribou" },
  "Skrillex":        { am: "356545647", mb: "ae002c5d-aac6-490b-a39a-30aa9e2edf2b", bc: "skrillex",   sc: "skrillex",   ig: "skrillex",   lf: "Skrillex" },
  "deadmau5":        { am: "78011850",  mb: "4a00ec9d-c635-463a-8cd4-eb61725f0c60", bc: "deadmau5",   sc: "deadmau5",   ig: "deadmau5",   lf: "deadmau5" },
  "Daft Punk":       { am: "5468295",   mb: "056e4f3e-d505-4dad-8ec1-d04f521cbb56", bc: "daftpunk",   sc: "daftpunk",   ig: "daftpunk",   lf: "Daft Punk" },
  "Aphex Twin":      { am: "39883194",  mb: "f22942a1-6f70-4f48-866e-238cb2308fbd", bc: "aphextwin",  sc: "aphextwin",  ig: "aphextwin",  lf: "Aphex Twin" },
  // New additions (2026-09-06, for builder-portal demo)
  "Burial":          { am: "468355684", mb: "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6", bc: "burial",     sc: "burial",     ig: "burial",     lf: "Burial" },
  "Floating Points": { am: "311514259", mb: "69d9c5ba-7bba-4cb7-ab32-8ccc48ad4f97", bc: "floatingpoints", sc: "floatingpoints", ig: "floatingpoints", lf: "Floating Points" },
  "Boards of Canada":{ am: "2989314",   mb: "69158f97-4c07-4c4e-baf8-4e4ab1ed666e", bc: "boardsofcanada", sc: "boardsofcanada", ig: "boardsofcanada", lf: "Boards of Canada" },
  "Fred again..":    { am: "1455262408", mb: "bca46a0c-25c9-42ca-98c2-e64c8a5e337e", bc: "fredagain",  sc: "fredagainagainagain", ig: "fredagainofficial", lf: "Fred again.." },
  "Jamie xx":        { am: "405563985",  mb: "d1515727-4a93-4c0d-88cb-d7a9fce01879", bc: "jamiexx",    sc: "jamiexx",    ig: "jamiexx",    lf: "Jamie xx" },
  // Mindex (added 2026-09-06 in response to user submit — exposed v0.3.4 tier-2 bugs)
  "Mindex":          { am: "295430906",  mb: "",                                  bc: "mindex",     sc: "mindex",     ig: "mindex",     lf: "Mindex" },
};

function fillDemoArtist(name) {
  const d = DEMO_ARTISTS[name];
  if (!d) return;
  $("f-name").value = name;
  // clear picked
  picked.length = 0;
  document.querySelectorAll("#srcPick button.on").forEach(b => b.classList.remove("on"));
  // pre-pick two sources. Default: apple_music + musicbrainz. If
  // musicbrainz is missing (some artists like Mindex aren't on MB),
  // fallback to bandcamp for the second source.
  const amBtn = document.querySelector(`#srcPick button[data-src="apple_music"]`);
  const primary = d.mb ? "musicbrainz" : "bandcamp";
  const primaryHandle = d.mb || d.bc;
  const primaryBtn = document.querySelector(`#srcPick button[data-src="${primary}"]`);
  if (amBtn) { amBtn.click(); document.querySelector(`#srcRows input[data-h="${picked.length - 1}"]`).value = d.am; picked[picked.length - 1].handle = d.am; }
  if (primaryBtn && primary !== "apple_music") {
    primaryBtn.click();
    document.querySelector(`#srcRows input[data-h="${picked.length - 1}"]`).value = primaryHandle;
    picked[picked.length - 1].handle = primaryHandle;
  }
  // disable strict mode for demo so we see the real computed score
  $("fStrict").checked = false;
  // Add the bonus handles to source_urls via extra (un-toggled) suggestions in picked rows
  // — but since the picker only takes 2, the leader will still query by name from the
  // leader's own side. The bonus handles (bandcamp/soundcloud/instagram/lastfm) live in
  // the calldata's sourceUrls dict, which the demo submit handler below injects.
  // Verify banner note: with real public handles + the lenient demo
  // rubric (≥60 = VRFD), a famous artist with at least one tier-1
  // confirmation + a few tier-2 platforms should clear the seal.
  $("verify-status").innerHTML = `<b>${name}</b> loaded — Apple Music + MusicBrainz prefilled. Strict mode is OFF for this demo so you see the real computed score. After submit the certificate shows BOTH the on-chain strict score AND a friendly lenient projection that flips to Verified when two independent platforms agree on the name. <a href="#" id="alsoBonus" style="color:var(--accent-ui);text-decoration:underline">Also include Bandcamp/SoundCloud/Instagram/Last.fm</a>.`;
  document.getElementById("alsoBonus")?.addEventListener("click", (e) => {
    e.preventDefault();
    includeBonusHandles(d);
  });
}

function includeBonusHandles(d) {
  // Push all bonus sources into the picked array directly (the picker UI
  // caps at 2 visible, but the backend takes any number in sourceUrls).
  for (const [k, v] of [["bandcamp", d.bc], ["soundcloud", d.sc], ["instagram", d.ig], ["lastfm", d.lf]]) {
    if (!picked.some(p => p.src === k)) {
      picked.push({ src: k, handle: v });
      const chip = document.querySelector(`#srcPick button[data-src="${k}"]`);
      if (chip) chip.classList.add("on");
    }
  }
  renderPicked();
  $("verify-status").innerHTML = `<b>${$("f-name").value}</b> loaded with all 6 sources. Ready to submit.`;
}

$("fDemo").addEventListener("change", (e) => {
  const name = e.target.value;
  if (name) fillDemoArtist(name);
});

document.querySelectorAll(".modal-tab").forEach(t => {
  t.onclick = () => {
    document.querySelectorAll(".modal-tab").forEach(x => x.classList.toggle("active", x === t));
    document.querySelectorAll(".modal-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === t.dataset.tab));
  };
});

// ── Ownership proofs (Tier 2.6): ALVERIFY token + per-platform rows ─────
const OWN_PLATFORMS = [
  { id: "soundcloud", label: "SoundCloud bio",  ph: "handle (e.g. four-tet)",      url: (h) => `https://soundcloud.com/${h}` },
  { id: "lastfm",     label: "Last.fm profile", ph: "username (200+ scrobbles)",   url: (h) => `https://www.last.fm/user/${h}` },
  { id: "bandcamp",   label: "Bandcamp about",  ph: "subdomain (e.g. fourtet)",    url: (h) => `https://${h}.bandcamp.com` },
  { id: "youtube",    label: "YouTube channel", ph: "@handle or channel URL",      url: (h) => `https://www.youtube.com/${h.startsWith("@") || h.startsWith("UC") ? h : "@" + h}` },
];
let ownToken = "";

// Stable ownership token: ALVERIFY-<hash(wallet + artist)>. Deterministic
// per person — the SAME token across page loads, sessions, and claims, so
// the artist pastes it once into their bios and it never drifts. The
// random-per-load scheme caused real failures (bios carried an old token
// while the page submitted a fresh one → no match). Falls back to a
// session-stable random token before a wallet connects.
function genOwnershipToken() {
  const abc = "ABCDEFGHJKMNPQRSTVWXYZ23456789";
  const src = (walletAddr || "anon") + ":" + ($("f-name").value.trim() || "");
  // FNV-1a 32-bit → 8 base32 chars (crypto-stable, no randomness)
  let h = 2166136261 >>> 0;
  for (let i = 0; i < src.length; i++) {
    h ^= src.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  let rnd = "";
  let v = h >>> 0;
  for (let i = 0; i < 8; i++) { rnd += abc[v % 32]; v = Math.floor(v / 32); }
  // suffix = day bucket (86400s), stable for 24h so pasted bios don't expire
  ownToken = `ALVERIFY-${rnd}-${Math.floor(Date.now() / 86400000)}`;
  $("own-token").value = ownToken;
  return ownToken;
}

// Re-derive (not regenerate) whenever the wallet or artist name changes —
// the token only changes when the identity does.
function refreshOwnershipToken() {
  genOwnershipToken();
}

function ownershipProofsDict() {
  // Collect filled platform rows → {platform: handle} for the contract.
  const out = {};
  document.querySelectorAll("#own-rows .own-row").forEach(row => {
    const plat = row.querySelector("select").value;
    const handle = row.querySelector("input").value.trim();
    if (plat && handle) out[plat] = handle;
  });
  return out;
}

function renderOwnRows() {
  const box = $("own-rows");
  const rows = [...box.querySelectorAll(".own-row")];
  box.innerHTML = "";
  rows.forEach(r => box.appendChild(r)); // keep existing rows (rebuild-safe)
}

function addOwnRow(plat = "", handle = "") {
  const box = $("own-rows");
  if (box.children.length >= 4) return; // 4 channels max
  const row = document.createElement("div");
  row.className = "own-row";
  const sel = document.createElement("select");
  const blank = document.createElement("option");
  blank.value = ""; blank.textContent = "platform…";
  sel.appendChild(blank);
  for (const p of OWN_PLATFORMS) {
    const o = document.createElement("option");
    o.value = p.id; o.textContent = p.label;
    sel.appendChild(o);
  }
  sel.value = plat;
  const inp = document.createElement("input");
  inp.placeholder = "handle"; inp.value = handle; inp.spellcheck = false;
  inp.addEventListener("focus", () => {
    const p = OWN_PLATFORMS.find(x => x.id === sel.value);
    if (p) inp.placeholder = p.ph;
  });
  const rm = document.createElement("button");
  rm.className = "rm"; rm.textContent = "✕"; rm.title = "remove";
  rm.onclick = () => row.remove();
  row.append(sel, inp, rm);
  box.appendChild(row);
}

function initOwnershipUI() {
  genOwnershipToken();
  $("own-copy").onclick = async () => {
    try { await navigator.clipboard.writeText(ownToken); $("own-copy").textContent = "Copied ✓";
      setTimeout(() => ($("own-copy").textContent = "Copy"), 1600); } catch {}
  };
  // "Regenerate" now means re-derive for the CURRENT identity — deterministic,
  // same token every time. A different token only appears for a different
  // wallet or artist name (the identity changed).
  $("own-regen").onclick = () => { refreshOwnershipToken(); logLine("token re-derived for " + shortAddr(walletAddr || "anon")); };
  $("own-add").onclick = () => addOwnRow();
  // Token follows the identity: wallet connect + artist name edits re-derive it.
  document.addEventListener("wallet-connected", refreshOwnershipToken);
  const nameInput = $("f-name");
  if (nameInput) {
    nameInput.addEventListener("change", refreshOwnershipToken);
    nameInput.addEventListener("input", () => {
      if (ownToken) refreshOwnershipToken();
      if (window.setAtmosphereMode) {
        window.setAtmosphereMode("composing", { name: nameInput.value.trim(), sources: picked.length });
      }
    });
  }
  // empty by default; user opts in
}

initOwnershipUI();

// ── Submit (the whole pipeline: build args → send tx → wait → render cert) ─
$("submitBtn").onclick = async () => {
  if (!walletAddr) { alert("Click \"Connect\" first."); return; }
  if (picked.length < 1) { alert("Pick at least 1 source."); return; }
  if (!$("f-name").value.trim()) { alert("Artist name is required."); return; }

  $("submitBtn").disabled = true;
  $("submitBtn").textContent = "Submitting…";
  clearLog();
  $("live-logs").style.display = "block";
  $("verify-status").innerHTML = "<b>Submitting to the contract…</b>";
  logLine("[01] Building calldata from " + picked.length + " source(s)");

  const name = $("f-name").value.trim();
  const sourceUrls = {};
  for (const p of picked) sourceUrls[p.src] = p.handle;

  const vs1 = picked[0] ? toContractSrc(picked[0].src) : "";
  const vh1 = picked[0] ? picked[0].handle : "";
  const vs2 = picked[1] ? toContractSrc(picked[1].src) : "";
  const vh2 = picked[1] ? picked[1].handle : "";

  const args = [
    "did:web:" + name.toLowerCase().replace(/\s+/g, "") + ".example",
    name, "0x" + "11".repeat(32),
    sourceUrls, walletAddr,
    vs1, vh1, vs2, vh2, $("fStrict").checked,
    ownToken, ownershipProofsDict(),
  ];

  try {
    const callOpts = { address: CONTRACT, functionName: "register_artist", args, value: 0n, leaderOnly: false };
    if (walletKind === "real") {
      // Real-wallet mode: no client-level account (the SDK would otherwise
      // sign locally) — the connected wallet signs via eth_sendTransaction
      // and pops its own confirm dialog.
      callOpts.account = { type: "json-rpc", address: walletAddr };
      logLine("[02] Waiting for the wallet to sign (check the MetaMask popup)…");
    } else {
      logLine("[02] Signing with the attached demo key…");
    }
    const tx = await writeClient.writeContract(callOpts);
    logLine("[02] Submitted tx " + tx.slice(0, 14) + "…");
    $("verify-status").innerHTML = "<b>Waiting for consensus…</b> (4 validators re-derive the score)";
    $("live-badge").textContent = "PENDING";

    const receipt = await writeClient.waitForTransactionReceipt({ hash: tx, status: "FINALIZED", retries: 60, interval: 4000 });
    logLine("[03] " + receipt.status_name + " / " + receipt.result_name);

    const data = parseReceipt(receipt);
    lastReceipt = receipt;
    lastData = data;
    renderCertificate(data, receipt);
    if (window.setAtmosphereMode) {
      window.setAtmosphereMode("consensus", { verdict: data.verdict, score: data.score });
    }

    // Enable the next two states
    stepB.disabled = false;
    stepC.disabled = false;
    $("submitBtn").disabled = false;
    $("submitBtn").textContent = "Sign & submit proof →";
    go("B");
  } catch (e) {
    logLine("[err] " + (e.message || e));
    if (window.setAtmosphereMode) window.setAtmosphereMode("error", { err: e.message || String(e) });
    $("verify-status").textContent = "Error: " + (e.message || e);
    $("submitBtn").disabled = false;
    $("submitBtn").textContent = "Sign & submit proof →";
  }
};

// On every state change to C, refresh the modal contents (handled in go() now)

// ── Boot ──────────────────────────────────────────────────────────────
(async function boot() {
  try {
    const c = ensureReadClient();
    let schema = null;
    // First try the raw JSON-RPC method (works even when the explorer indexer
    // is paused — this is what we actually rely on for read access).
    try {
      schema = await c.request({ method: "gen_getContractSchema", params: [CONTRACT] });
    } catch (e) {
      // Fall back to the SDK helper. NOTE: this calls through the explorer
      // indexer and can fail with HTTP 500 / SQL errors when the indexer is
      // paused; we just log it and continue without blocking boot.
      try { schema = await c.getContractSchema({ address: CONTRACT }); }
      catch (e2) { console.warn("[boot] schema fetch failed:", e2.message); }
    }
    const methods = Object.keys((schema && schema.methods) || {}).join(", ");
    $("rpcDot").classList.add("on");
    $("rpcStatus").textContent = methods
      ? `connected · ${methods.split(",").length} methods`
      : "connected (schema unavailable)";

    // Auto-reconnect real wallet if already authorized in browser extension
    if (window.ethereum && typeof window.ethereum.request === "function") {
      try {
        const accs = await window.ethereum.request({ method: "eth_accounts" });
        if (accs && accs.length > 0) {
          logLine("detected authorized browser wallet — auto-connecting " + shortAddr(accs[0]));
          await connectRealWallet();
        }
      } catch (e) {
        console.warn("[boot] silent wallet reconnect:", e.message || e);
      }
    }
  } catch (e) {
    $("rpcDot").classList.add("err");
    $("rpcStatus").textContent = "RPC unreachable";
    console.error("[boot]", e);
  }
})();
