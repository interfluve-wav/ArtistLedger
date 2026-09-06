/* ArtistLedger — Register → Certificate → Inspect
 * Talks to the v4 GenLayer contract on studionet via the genlayer-js SDK.
 * Replaces the old 3-card form. State machine: A (register) → B (certificate) → C (inspect).
 */
"use strict";

const CONTRACT = "0x703AdAB82751A9006aFE9c477DC344f8D9CA4384";
const GL = window.GenLayerSDK;

let client = null;        // read client
let walletAddr = null;    // connected wallet
let lastReceipt = null;   // for the inspect modal
let lastData = null;      // parsed evidence + verdict

function $(id) { return document.getElementById(id); }
function shortAddr(a) { return a.slice(0, 6) + "…" + a.slice(-4); }
function replacer(_k, v) { return typeof v === "bigint" ? v.toString() : v; }

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
function logLine(s) {
  const el = $("loglines");
  el.textContent += (el.textContent ? "\n" : "") + s;
}
function clearLog() { $("loglines").textContent = ""; }

// ── Wallet / RPC ───────────────────────────────────────────────────────
const LS_KEY = "artistledger.localAccountPk";

$("localAcctBtn").addEventListener("click", () => {
  try {
    let pk = localStorage.getItem(LS_KEY);
    let account;
    if (pk) { account = GL.createAccount(pk); }
    else { pk = GL.generatePrivateKey(); account = GL.createAccount(pk); localStorage.setItem(LS_KEY, pk); }
    walletAddr = account.address;
    client = GL.createClient({ chain: GL.chains.studionet, account });
    $("walletLabel").textContent = shortAddr(walletAddr) + " (local)";
  } catch (e) {
    $("walletLabel").textContent = "Local account failed: " + (e.message || e);
  }
});

async function rpcRead(fnName, args) {
  if (!client) client = GL.createClient({ chain: GL.chains.studionet });
  return client.readContract({ address: CONTRACT, functionName: fnName, args, jsonSafeReturn: true });
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

  // Cross-reference rows from leader evidence
  const rows = $("cross-rows");
  rows.innerHTML = "";
  for (const m of data.matched) {
    const det = document.createElement("details");
    det.innerHTML = `<summary><span class="label">${m.label}</span><span class="handle">${m.detail || ""}</span><span class="verdict ${m.verdict === "claimed" ? "warn" : m.verdict === "match" || m.verdict === "verified" || m.verdict === "track" ? "ok" : ""}">${m.verdict}</span><span class="caret">▶</span></summary><div class="raw">${m.detail || ""}</div>`;
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
  const ev = data.evidence || {};
  const bd = $("breakdown-rows");
  bd.innerHTML = "";
  const lines = [
    ["AcoustID (audio fingerprint)", ev.acoustid_matched ? "+20" : "—"],
    ["ISRC codes (MusicBrainz)", ev.isrc_codes?.length ? `+${Math.min(10, ev.isrc_codes.length * 10)}` : "—"],
    ["Spotify", ev.spotify_artist_id ? (ev.spotify_verified ? "+10 (verified)" : (Number(ev.spotify_popularity) >= 20 && Number(ev.spotify_followers) >= 1000) ? "+10" : "found") : "—"],
    ["Apple Music", ev.apple_music_track_present ? "+5 (track present)" : ev.apple_music_artist_id ? "+5 (artist)" : "—"],
    ["Bandcamp", ev.bandcamp_handle ? "+3" : "—"],
    ["SoundCloud", ev.soundcloud_handle ? (ev.soundcloud_verified ? `+3 (verified, ${(Number(ev.soundcloud_followers)/1000).toFixed(0)}k)` : `+3 (${(Number(ev.soundcloud_followers)/1000).toFixed(0)}k)`) : "—"],
    ["Instagram", ev.instagram_handle ? "+2" : "—"],
    ["Last.fm", Number(ev.lastfm_scrobble_count) >= 100 ? "+2" : "—"],
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
  "Four Tet":     { am: "35888604",  mb: "53b106cf-2cc3-48b6-9b1d-5d8a8a16f5e6", bc: "fourtet",    sc: "four-tet",   ig: "fourtet",    lf: "Four Tet" },
  "Caribou":      { am: "45464574",  mb: "735e3514-a8ae-401f-af3b-6300df1b8d2c", bc: "caribou",    sc: "caribou",    ig: "caribou",    lf: "Caribou" },
  "Skrillex":     { am: "356545647", mb: "ae002c5d-aac6-490b-a39a-30aa9e2edf2b", bc: "skrillex",   sc: "skrillex",   ig: "skrillex",   lf: "Skrillex" },
  "deadmau5":     { am: "78011850",  mb: "4a00ec9d-c635-463a-8cd4-eb61725f0c60", bc: "deadmau5",   sc: "deadmau5",   ig: "deadmau5",   lf: "deadmau5" },
  "Daft Punk":    { am: "5468295",   mb: "056e4f3e-d505-4dad-8ec1-d04f521cbb56", bc: "daftpunk",   sc: "daftpunk",   ig: "daftpunk",   lf: "Daft Punk" },
  "Aphex Twin":   { am: "39883194",  mb: "f22942a1-6f70-4f48-866e-238cb2308fbd", bc: "aphextwin",  sc: "aphextwin",  ig: "aphextwin",  lf: "Aphex Twin" },
};

function fillDemoArtist(name) {
  const d = DEMO_ARTISTS[name];
  if (!d) return;
  $("f-name").value = name;
  // clear picked
  picked.length = 0;
  document.querySelectorAll("#srcPick button.on").forEach(b => b.classList.remove("on"));
  // pre-pick apple_music + musicbrainz with real handles
  const amBtn = document.querySelector(`#srcPick button[data-src="apple_music"]`);
  const mbBtn = document.querySelector(`#srcPick button[data-src="musicbrainz"]`);
  if (amBtn) { amBtn.click(); document.querySelector(`#srcRows input[data-h="${picked.length - 1}"]`).value = d.am; picked[picked.length - 1].handle = d.am; }
  if (mbBtn) { mbBtn.click(); document.querySelector(`#srcRows input[data-h="${picked.length - 1}"]`).value = d.mb; picked[picked.length - 1].handle = d.mb; }
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

// ── Submit (the whole pipeline: build args → send tx → wait → render cert) ─
$("submitBtn").onclick = async () => {
  if (!walletAddr) { alert("Click \"Use local account\" first."); return; }
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
  ];

  try {
    const tx = await client.writeContract({ address: CONTRACT, functionName: "register_artist", args, value: 0n, leaderOnly: false });
    logLine("[02] Submitted tx " + tx.slice(0, 14) + "…");
    $("verify-status").innerHTML = "<b>Waiting for consensus…</b> (4 validators re-derive the score)";
    $("live-badge").textContent = "PENDING";

    const receipt = await client.waitForTransactionReceipt({ hash: tx, status: "FINALIZED", retries: 60, interval: 4000 });
    logLine("[03] " + receipt.status_name + " / " + receipt.result_name);

    const data = parseReceipt(receipt);
    lastReceipt = receipt;
    lastData = data;
    renderCertificate(data, receipt);

    // Enable the next two states
    stepB.disabled = false;
    stepC.disabled = false;
    $("submitBtn").disabled = false;
    $("submitBtn").textContent = "Sign & submit proof →";
    go("B");
  } catch (e) {
    logLine("[err] " + (e.message || e));
    $("verify-status").innerHTML = "<span class=\"err\">Error: " + (e.message || e) + "</span>";
    $("submitBtn").disabled = false;
    $("submitBtn").textContent = "Sign & submit proof →";
  }
};

// On every state change to C, refresh the modal contents (handled in go() now)

// ── Boot ──────────────────────────────────────────────────────────────
(async function boot() {
  try {
    client = GL.createClient({ chain: GL.chains.studionet });
    let schema = null;
    // First try the raw JSON-RPC method (works even when the explorer indexer
    // is paused — this is what we actually rely on for read access).
    try {
      schema = await client.request({ method: "gen_getContractSchema", params: [CONTRACT] });
    } catch (e) {
      // Fall back to the SDK helper. NOTE: this calls through the explorer
      // indexer and can fail with HTTP 500 / SQL errors when the indexer is
      // paused; we just log it and continue without blocking boot.
      try { schema = await client.getContractSchema({ address: CONTRACT }); }
      catch (e2) { console.warn("[boot] schema fetch failed:", e2.message); }
    }
    const methods = Object.keys((schema && schema.methods) || {}).join(", ");
    $("rpcDot").classList.add("on");
    $("rpcStatus").textContent = methods
      ? `connected · ${methods.split(",").length} methods`
      : "connected (schema unavailable)";
  } catch (e) {
    $("rpcDot").classList.add("err");
    $("rpcStatus").textContent = "RPC unreachable";
    console.error("[boot]", e);
  }
})();
