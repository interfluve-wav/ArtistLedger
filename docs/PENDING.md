# v0.3.3 — Pending work

This document tracks the work that needs to land before the contract is
usable on testnet for real artist registrations. Items are ordered by
expected impact on verification correctness.

## Done in v0.3.3

- **API key admin setter.** Added 4 storage fields
  (`acoustid_key`, `spotify_token`, `lastfm_key`, `etherscan_key`) and
  a `@gl.public.write set_api_keys(...)` admin method. The four
  module-level helpers now take their key as a parameter. Unguarded
  for testnet; production needs an admin-address gate.
- **Explicit `Evidence.to_dict()` for validator calldata round-trip.**
  Added an explicit `to_dict()` method that converts `DynArray` to
  `list` and `u256` to `int`. `to_json` now routes through `to_dict`,
  so the validator's `json.loads(leader_result.calldata)` path works
  for any JSON-string wire format.

## Required before testnet deploy

*(none — the two required items have landed in v0.3.3)*

## Required before broad release (not blocking testnet)

### 3. Spotify `verified` field

**Where:** `contracts/ProvenanceRegistry.py` — line ~519, the
`_spotify_search` parser.

**Risk:** Public Spotify Web API search does not return a `verified`
boolean on artist objects. The current parser sets `ev.spotify_verified
= bool(sp.get("verified", False))` which will always be `False`.
Scoring falls back to `popularity >= 20 AND followers >= 1000`,
which works for real artists but under-credits actually-verified
accounts.

**Fix:** Either drop the `verified` branch and only use popularity +
followers, or do a follow-up `GET /v1/artists/{id}` call to get the
verified flag. The follow-up is a second API call inside the leader
function (still in `run_nondet_unsafe`).

### 4. Apple Music `wrapperType` field

**Where:** `contracts/ProvenanceRegistry.py:241-253` — the
`_apple_music_search` function.

**Risk:** iTunes Search API does not return `wrapperType`. Current
parser will not match any iTunes Search response. The newer Apple
Music API does return `wrapperType` but requires a developer JWT
that we don't have a flow for.

**Fix:** Switch the parser to iTunes Search's actual fields
(`kind: "song" | "music-video" | ...`, `artistId`, `trackId`). Drop
the `wrapperType` branch. If the contract ever needs to query Apple
Music proper (with track-level metadata), implement the JWT flow
separately.

### 5. Bandcamp / SoundCloud / Instagram HTML scraping

**Where:** `contracts/ProvenanceRegistry.py:258-299` — three
`_bandcamp_check`, `_soundcloud_check`, `_instagram_check`
functions.

**Risk:** Not APIs. Will break the moment any of these sites change
their HTML structure. Real-name, location, follower count, and
verified badge are all parsed out of the page body via regex.

**Fix:** Reduce each to a 200-vs-404 existence check on the URL
(handle round-trip only). Drop the `_regex_first` calls and the
real-name/location/followers/verified fields from the parsed
evidence. If richer data is needed later, use the official Bandcamp
artist API (private) or a scraping service like Apify.

### 6. Farcaster endpoint

**Where:** `contracts/ProvenanceRegistry.py:371-379` — the
`_farcaster_fname` function.

**Risk:** Calls `https://api.farcaster.xyz/v2/user-by-cast-address`,
which is not a public Farcaster Hub path. Real Hub endpoints are on
`hub.farcaster.xyz:2281` with gRPC-style requests, or via hosted
Hub APIs like `api.farcaster.xyz` (note: not the URL we're calling)
with different request shapes.

**Fix:** Use a real Farcaster fname lookup service. Options:
- Neynar (`https://api.neynar.com/v2/farcaster/user/bulk-by-address`)
  if we add a key
- Farcaster Hub on a hosted endpoint with the correct path

For testnet, we can stub the field or use the Neynar endpoint with
a key.

## Cosmetic

### 7. Bump docstring headers

**Where:** `contracts/ProvenanceRegistry.py:3`,
`tests/test_provenance.py:2`.

**Change:** `OnChainProvenanceRegistry — GenLayer Intelligent
Contract v0.2.0` → `v0.3.3` (or whatever ships). Cosmetic but visible
to reviewers.

## Process

Items 1 and 2 are required for any testnet deploy to be useful.
Items 3-6 are about correctness of the verification scoring under
real-world data. Item 7 is cosmetic.

When work begins, copy this file's contents to `docs/v0.3.3.md` (or
`docs/CHANGELOG.md` v0.3.3 entry) and clear the corresponding section
here.

---

# v0.3.4 — Two-source verification (in progress, `feat/v0.3.4-twosource`)

## Layer 1 — IMPLEMENTED (Apple Music fix + two-source fields/scoring)

- `_apple_music_search` fixed: `entity=musicTrack&limit=5` + `name in
  artistName` co-artist guard (Layer 0). `W_APPLE_MUSIC` now awardable.
- New `Evidence` fields: `verification_source_1/2`, `verification_handle_1/2`
  (str), `verification_match_count` (u256).
- New weights `W_TWO_SOURCE_MATCH=15`, `W_SINGLE_SOURCE_MATCH=8`; Tier-2
  rebalanced (bandcamp/soundcloud 5→3, instagram 5→2, lastfm 5→2).
- `register_artist` takes 4 optional two-source args (defaults "").
- `_verify_claimed_source` dispatches on the DISCO 13-enum; resolves
  Spotify/Apple/Bandcamp/SoundCloud/Instagram; claim-only sources
  (TikTok/Tidal/Facebook/website/Twitter/YouTube) return False → Layer 2.
- Scoring: 2 matches → `W_TWO_SOURCE_MATCH`, 1 match → `W_SINGLE_SOURCE_MATCH`.

## Layer 2 — TODO: TikTok + Tidal + IPI + Facebook + website real checks

Extend `_verify_claimed_source` so claim-only sources get real checks:
- TikTok: scrape `tiktok.com/@{handle}` embedded JSON (followerCount + name)
- Tidal: 200-check artist URL
- IPI: ISO 7172 mod-101 checksum validation (`W_IPI` when valid)
- Facebook: 200-check (HTML not parseable without login)
- website: 200-check + cross-ref regex for bandcamp/spotify/discogs links

## Layer 3 — Two-source strict mode (configurable)

New `Artist.require_two_source: bool`. When True, score capped ≤5 unless
`verification_match_count >= 2` — registration effectively rejected at
consensus unless both claimed sources match.

## Layer 4 — find_artist.py updates

Add `--disco-mode` (emit DISCO step-5 JSON shape) and `--two-source-report`.

## Future: make validation more real/proper (oAuth)

Current model is claim-and-cross-reference: the artist pastes URLs, the
leader/validators fetch them. It's spoofable if someone owns fake URLs.

Real-identity upgrade (highest impact):
- **OAuth linking (Spotify / SoundCloud, then Apple Music)** — artist
  authorizes via OAuth, the leader grabs the canonical verified profile
  + an oAuth token that proves possession of the account. This is the
  strongest anti-impersonation signal short of the signed tx.
- Requires a backend holder for the oAuth client secret + token exchange
  (can't hold secrets on-chain), then the contract verifies a signed
  attestation that the oAuth id matches the claimed name.
- Scope: adds a `connect(provider, token_attestation)` method on the
  contract + a small off-chain oAuth broker (e.g. as a Hermes-adjacent
  service or separate `provenance-oauth` repo).

Deferred (lower priority): EAS attestations, Apple JWT, Farcaster via
Neynar, ENS text records (v0.3.5).

## Validator / provider catalog (DISCO parity — kept current)

The on-chain validator (`_score_evidence`, `leader_collect`) currently
binds against these sources:
- Spotify (search API, Bearer key) — tier 1
- Apple Music / iTunes Search — tier 1
- Bandcamp, SoundCloud, Instagram — tier 2 (HTML scraped)
- Last.fm (scrobble count via `ws.audioscrobbler.com`, key) — tier 2
- MusicBrainz (artist + ISRC + recording) — tier 1 (evidence)
- AcoustID (audio fingerprint) — tier 1
- ENS + Etherscan + Farcaster — wallet-derived

Claim-only (via two-source, pending Layer 2): TikTok, Tidal, Facebook,
website, Twitter, YouTube, IPI.
