# Future Planning — v0.4+ ideas

Status: brainstorm, not scoped. Items below were discussed 2026-09-05 as
follow-ups to v0.3.4. All are designed to fit the existing architecture
(Evidence field + weight + collector in `_score_evidence`, everything runs
inside GenLayer's leader/validator consensus) — no new infra, no oracles.

## A. Authenticity batch (recommended first)

Core insight from v0.3.4 review: current checks prove *existence* ("this
profile/page exists") and *catalog presence* ("this audio is in a
database"), not *authorship*. The stronger axes are **time, mutual
references, and things that cost money** — none fakeable retroactively.

### A1. AcoustID credit flip — "who does the database say made it?" (priority 1)

AcoustID answers "does this audio exist in the public fingerprint DB?" —
weak, because anyone can fingerprint someone else's track. Flip it into an
anti-impersonation gate:

- After `_acoustid_lookup` returns the mbid, one extra query to
  MusicBrainz (same endpoint we already use for ISRCs, add
  `inc=artist-credits`) fetches the credited artist. Keyless.
- Compare credited name vs claimed name via `_name_token_overlap`:
  - overlap >= 0.5 → keep W_ACOUSTID (now genuinely earned)
  - no overlap → `acoustid_credit_mismatch = True` → hard-cap score below
    threshold (same cap pattern as strict-mode). Registering someone
    else's audio under your name = automatic rejection.
  - MB has no credit for the recording (patchy data) → no signal, no
    punishment.
- Edge cases: remixes credit the original artist; various-artists credits
  → check overlap against any credited name. Cap-not-ban, mismatch stored
  in evidence JSON for dispute review.
- Size: ~15-line helper, 2 Evidence fields, 1 scoring branch. No keys.

### A2. Wayback Machine presence age (+5)

archive.org availability API, keyless: "when was this artist's
Bandcamp/website first archived?" A profile claiming a 10-year career but
first archived last month fails. Past archives cannot be forged.

- New helper `_web_presence_years(url)` — one `gl.nondet.web.get` to
  `http://archive.org/wayback/available?url=...` + timestamp query.
- New Evidence field `web_presence_years`, new weight W_WAYBACK = 5.

### A3. did:web domain control (+5)

`register_artist` already accepts a DID. If `did:web:example.com`, fetch
`example.com/.well-known/artist.json` and check it names the artist +
wallet. Domains cost money and age — keyless, hard to fake at scale.

- One GET, new Evidence field `did_web_verified`, weight +5.
- Validates a field we currently accept on faith.

## B. Mutual bio cross-linking (+5)

Fake profile farms rarely wire mutual links between their fake profiles.

- `_bandcamp_check` / `_soundcloud_check` already fetch page HTML (we
  throw away everything but name/followers).
- New helper `_count_cross_links(bandcamp_body, soundcloud_body,
  ig_handle, ...)` — pure string matching on already-fetched bodies, zero
  new HTTP calls:
  - Bandcamp body contains `soundcloud.com/{claimed_sc}` or
    `instagram.com/{claimed_ig}`?
  - SoundCloud body links back to the claimed Bandcamp?
- Mutual pair = +5, one-way = +2 (capped). Real artists often link only
  one way, so don't require mutual.
- Contract only awards points for links between profiles *in the same
  submission* — can't link to random real artists.
- Consensus-friendly: deterministic string matching, validators re-execute
  and agree.
- Size: ~30 lines — 1 helper, 1 Evidence field (`cross_links_found`),
  1 weight, 1 scoring line.

## C. Proof-of-control challenge (strongest ownership signal)

Proves *ownership* of a profile, not just existence — the same thing
Spotify/DISCO OAuth achieves, done with plain web scraping.

- Two transactions:
  1. `challenge_profile(wallet, source, handle)` → contract stores a
     random code (e.g. `PRVN-8f3a2c`) + expiry (24h) on the Artist record
  2. artist pastes the code into their bio; `verify_challenge()` →
     validators re-fetch the page, look for the code, match → award
     points / upgrade verification status.
- Whoever can edit the profile controls it. Unfakeable without owning
  the account.
- Size: ~40 lines, new `challenge` / `challenge_expires` fields on Artist,
  2 new methods.

## D. Attestations / vouch (trust graph)

- An artist already verified in the registry vouches for a newcomer:
  `vouch(wallet)` method, one line of storage.
- Fake newcomers can't buy vouchers: vouching puts the voucher's own
  reputation at risk (the existing dispute penalty already punishes bad
  vouchers).
- Trust graph grows from within the registry.

## E. Search-result sanity (reverse findability check)

- Search the claimed artist name via a search endpoint validators fetch;
  if none of the artist's claimed URLs appear in top results for their
  own name, flag it.
- Real artists are findable under their own name.

## F. Release history consistency

- Discogs (already used in find_artist.py, keyless) says 12 releases
  since 2018 but the artist claims a career started 2024 with 2 releases
  → mismatch flags a fabricated profile.

## G. Wallet music activity

- Extends the wallet-age signal: does the wallet's transaction history
  (Etherscan, key already required) show music-related contract activity
  (NFT royalties, Sound.xyz, Catalog)? A music wallet looks different
  from a fresh empty one.

## H. oAuth linking (deferred, needs off-chain broker)

- Spotify / SoundCloud / Apple Music OAuth: artist authorizes, leader
  grabs canonical verified profile + token proving account possession.
- Requires a backend holder for the client secret + token exchange
  (secrets can't live on-chain), then the contract verifies a signed
  attestation that the OAuth id matches the claimed name.
- Scope: adds a `connect(provider, token_attestation)` method.
- Note: proof-of-control (C) gets 80% of this value with no OAuth infra —
  do C first, OAuth later if ever.

## Roadmap-derived ideas (added 2026-09-05, from genlayer.com/blog/genlayer-roadmap-to-mainnet)

### R1. Position for the Mainnet migration (Bradbury → Clarke)
The roadmap (Dec 2025) names testnets Asimov (infra, volatile),
**Bradbury (AI focus, for validators/builders)** and **Clarke (mainnet
release candidate, stable, subsidized)**. We're on **studionet** (Studio's
simulated chain, 61999) — not any official testnet. Near-term action
belongs in R1a; the rest are direction-setting.

- **R1a. Re-deploy onto an official testnet before mainnet.**
  stduionet is fine for dev, but the roadmap's fee work ("gas, penalties
  and rewards... final step") means our zero-gas studionet writes will
  cost real gas on mainnet. Testnet-Clarke (stable, subsidized) is the
  natural pre-mainnet home. Keep the contract GenVM-compatible — the
  existing fixes already pass Studio's v0.2.16 GenVM, and that interface
  is stable across testnets.
- Fee budgeting: `register_artist` fires 8+ live HTTP calls per validator;
  on a fee network, validators pay for those. Consider minimizing
  non-deterministic calls and caching evidence — becomes a real design
  constraint, not a free-for-all.

### R2. Expose the protocol's appeal/tribunal path
The roadmap's centerpiece is Optimistic Democracy: commit-and-reveal,
rotations, **appeals**. Our `dispute()` is a single LLM judge with a
fixed verdict. If a dispute is dismissed (or an appeal is justified), the
network itself has an appeal path. Frontend/contract idea: an
`appeal(txId)` flow so a rejected claimant can route to the protocol's
own appeal mechanics instead of our one-judge verdict being final.

### R3. Greybox plugin for validator sanity (LUA middleware)
GenVM validators can run optional **greyboxing** LUA scripts to sanity-
check non-deterministic results before accepting. A greybox script that
bounds our evidence (reject absurd follower counts, clamp LLM judge
outputs ±5, reject degenerate scores) would make our contract easier for
validators to accept and reduce the UNDETERMINED drift we saw on
studionet.

### R4. LayerZero bridge — provenance as cross-chain infra
Per "Opening GenLayer to All Blockchains" (Dec 2025): GenLayer +
LayerZero lets Intelligent Contracts feed real-world data to *any* chain.
ArtistLedger could become an oracle: register/verify on GenLayer, then
post a signed verdict ("this artist/audio is human, score 82, evidence
hash ...") cross-chain via LayerZero. Turns the app into infra
(provenance-as-a-service) — the natural mainnet-native end state. Large
scope; park until the core is on an official testnet.

(These are direction-setting; A–H above remain the scoped v0.4 work
items. R1a is the only near-term action.)

## Not pursued

- **On-chain AI-audio detection** (spectral artifact checks): unreliable
  and GenVM can't do DSP. Keep as an off-chain example script at best.
- **Audius**: barely anyone uses it (user decision, 2026-09-04).

## Priority order (recommended)

1. A1 (AcoustID flip) — fixes the weakest signal, cheapest
2. C (proof-of-control) — the only item that proves ownership
3. B (mutual cross-links) — ~30 lines, free signal
4. A2 (Wayback) — strongest unfakeable time signal
5. A3 (did:web) — validates a field accepted on faith today
6. D, E, F, G as capacity allows; H last (infra-heavy)
