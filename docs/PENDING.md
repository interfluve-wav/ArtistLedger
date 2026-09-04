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

### 4. Apple Music `limit=1` (not `wrapperType`)

**Where:** `contracts/ProvenanceRegistry.py:262-274` — the
`_apple_music_search` function URL.

**Risk (real one):** Current URL is
`?entity=musicArtist,musicTrack&limit=1`. iTunes Search returns the
single most-relevant result for a `name+title` query, which is the
**artist** (more specific). The track branch is never hit, so
`ev.apple_music_track_present` stays `False` and `W_APPLE_MUSIC` is
never awarded. This is a scoring zero-out bug, not a parser bug.

**NOT a bug:** the `wrapperType: "artist"` and `wrapperType: "track"`
branches in the parser are correct. iTunes Search *does* return those
fields. The parser is fine.

**Fix:** Change `entity=musicArtist,musicTrack&limit=1` to
`entity=musicTrack&limit=5`. Pull `artistId` from the first track
result (every track has one). `track_present = bool(results)`. Add
a guard: if `name in r.get("artistName", "")` to avoid false matches
on co-artist tracks.

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

# v0.3.4 — DISCO signup parity (drafted 2026-09-04)

## Why this scope

Two probes (browser-driven, real form submission on `accounts.disco.ac`
plus JS bundle analysis of `static.disco.ac/disco-app/app-*.min.js`)
showed that DISCO's own artist onboarding requires a **claim-and-
cross-reference** trust model: the artist supplies their email and
band name, claims a `*.disco.ac` subdomain, then **provides two
verification sources** from a fixed enum (Instagram, Spotify, TikTok,
website, IPI, Facebook, SoundCloud, Apple Music, Bandcamp, Tidal,
Twitter, YouTube, Other). DISCO validates the artist can plausibly
claim both sources before activating the account.

This is the same trust model our contract uses — claim + cross-
reference — but DISCO's UX forces two sources, ours only uses
public-data aggregators. v0.3.4 closes the gap: require two named
verification sources, score higher when both cross-reference cleanly,
and add the three sources we currently skip (TikTok, IPI, website).

## DISCO's actual signup schema (extracted from production JS)

Source: `https://accounts.disco.ac/signup` rendered by
`static.disco.ac/disco-app/app-e317412d8e459ca6.min.js` (3.7 MB),
inside `t.useSignupTypes`. The schema below is verbatim from the
bundle — not a guess.

**Step 1 — Email**
- `email: string` (required)
- submit: "Start a free trial"

**Step 2 — Tell us a bit about you**
- `fullName: string` (required)
- `userType: "artist" | "business"` (required)

**Step 3 (artist path) — Tell us about your work**
- `business_name: string` — Artist/Band Name (API field is named
  `business_name` even for artists; this is the band's claimed name)
- `subdomain: string` — the unique `*.disco.ac` subdomain claim

**Step 4 (artist path) — Tell us about your work**
- `user_role: "artist" | "band" | "composer" | "producer"
  | "engineer" | "songwriter"` (required)

**Step 5 — Almost there! Final step (two-source verification)**
- `verification_source_1: enum` from
  `[instagram_handle, spotify_url, tiktok_handle, website_url,
  ipi_number, facebook_url, soundcloud_url, apple_music_url,
  bandcamp_url, tidal_music_url, twitter_handle, youtube_url,
  other_description]`
- `verification_handle_1: string` (the value for source 1)
- `verification_source_2: enum` (same list, must differ from source 1)
- `verification_handle_2: string`
- `termsAcceptance: bool` (required true)
- optional email opt-in checkbox

**Wire format:** every step POSTs to `https://accounts.disco.ac/api/signup/`
with `Content-Type: application/json`, `credentials: "include"` (uses
the `sessionid` cookie), body is the step's fields. Multi-part
`FormData` is used only if `logo` is present (skip — not artist path).
Auth is **not** OAuth for artist onboarding — DISCO sends an email
verification code after the two-source step. The sessionid cookie is
the auth credential for the duration of the flow.

**Why this matters for us:** DISCO's enum of 13 verification sources
is a sensible whitelist. Our v0.3.3 contract handles 7 of them
(Spotify, Apple Music, Bandcamp, SoundCloud, Instagram, Twitter,
YouTube). v0.3.4 adds the 3 we skip (TikTok, Tidal, IPI) and
implements the two-source validation pattern.

### Schema mapping: DISCO → OnChainProvenanceRegistry

| DISCO field | OnChainProvenanceRegistry equivalent |
|---|---|
| `email` | not stored on chain (off-chain in registration tx metadata) |
| `fullName` | `Artist.display_name` |
| `userType: "artist"` | implicit (only artists can register) |
| `business_name` | `Artist.canonical_name` |
| `subdomain` | `Artist.handle` (the artist-chosen string) |
| `user_role` | **dropped** — role enum was vestigial DISCO copy; artists, composers, producers, songwriters all use the same `register_artist` flow, distinguished only by which sources cross-reference (e.g. a composer has ASCAP writer records but no Spotify artist page). No field, no enum, no score. |
| `verification_source_1` + `verification_handle_1` | new `Evidence.verification_source_1: str` + `verification_handle_1: str` |
| `verification_source_2` + `verification_handle_2` | new `Evidence.verification_source_2: str` + `verification_handle_2: str` |
| `termsAcceptance` | not on chain (off-chain user agreement) |

## Trust-model parity

| | DISCO | Our contract |
|---|---|---|
| Source count required | 2 (must differ) | 0 currently — public-data only |
| Cross-reference method | Server-side opaque check | Leader runs public API calls, validator re-runs |
| OAuth? | No (email magic link) | No |
| Subdomain / identifier | `*.disco.ac` claim | on-chain `Artist` storage keyed by wallet |
| Upgrade path | 1 PRO can add IPI gating | Validator re-runs in `run_nondet_unsafe` |

The two-source pattern is the strongest possible claim-and-cross-
reference signal. With two independent public sources agreeing on the
artist name, the trust cost of impersonation is "forge two real
accounts on two real platforms under the same display name" — much
harder than forging one.

## Plan (5 layers, each ships in its own commit)

### Layer 0 — Apple Music `limit=1` fix (cleanup, prerequisite)

The real Apple Music bug. See item 4 above. One-line URL change
plus a `name in artistName` guard against co-artist false matches.
~10 lines of code, no new Evidence fields.

### Layer 1 — Two-source verification fields + scoring

- New `Evidence` fields:
  - `verification_source_1: str` (one of the 13-enum values)
  - `verification_handle_1: str`
  - `verification_source_2: str`
  - `verification_handle_2: str`
  - `verification_match_count: u256` (0/1/2)
- New scoring weights:
  - `W_TWO_SOURCE_MATCH = 15` if both sources validate AND name
    matches across both
  - `W_SINGLE_SOURCE_MATCH = 8` if exactly one source validates
- Rebalance Tier 2 down to keep 100 deterministic cap:
  - `W_BANDCAMP: 5 → 3`, `W_SOUNDCLOUD: 5 → 3`, `W_INSTAGRAM: 5 → 2`,
    `W_LASTFM: 5 → 2`. Net: 7 points freed for the new weights.
- New `register_artist` args: `verification_source_1`,
  `verification_handle_1`, `verification_source_2`,
  `verification_handle_2`. All default to `""`.
- Leader logic: for each non-empty source, look up the platform
  (existing helpers for Spotify, Bandcamp, SoundCloud, Instagram,
  Twitter, YouTube, Apple Music; new helpers for TikTok, Tidal, IPI,
  Facebook, website in Layer 2). Count how many match the artist
  name. Set `verification_match_count`. Award the appropriate weight.

### Layer 2 — TikTok + Tidal + IPI + Facebook + website helpers

- `_tiktok_user(handle)`: public HTML scrape of
  `https://www.tiktok.com/@{handle}` — extract `followerCount` and
  display name from the embedded JSON in `<script id="__UNIVERSAL_DATA">`.
  No API key needed.
- `_tidal_artist(url)`: Tidal has no public API. Fall back to 200-check
  on the artist URL. Set `ev.tidal_url_present` only.
- `_ipi_lookup(number)`: per-PRO endpoints (ASCAP, BMI, GEMA, PRS,
  SACEM, SIAE, JASRAC, APRA, etc.) each have a public search-by-name
  or search-by-IPI form. The simplest cross-PRO check: parse the IPI
  number itself. Valid IPI is 11 digits with a checksum (ISO 7172
  mod-10). Implement the checksum and award `W_IPI_VALID` if it
  passes. The lookup-by-name is per-PRO and out of scope for the
  contract (varied and slow).
- `_facebook_url(url)`: 200-check only. Facebook's HTML is JS-heavy
  and the data isn't parseable without login.
- `_website_url(url)`: 200-check + `data-bandcamp` / `data-discogs`
  / `data-spotify` lookalike regex on the homepage HTML to find
  cross-reference links. Optional signal.

### Layer 3 — Two-source strict mode (configurable)

A new `Artist` field: `require_two_source: bool` (set by the artist
at registration time, default `True`). When `True`:
- If `verification_match_count < 2`, the leader returns score capped
  at the LLM-adjustment floor (≤ 5). Registration is effectively
  rejected at the consensus level.
- When `False` (legacy): existing single-source scoring applies, with
  bonus points for the second source if it validates.

This gives artists a choice: strict two-source (high trust, more
work) or relaxed single-source (low trust, easy onboarding). Matches
DISCO's behavior where the two-source requirement is mandatory.

### Layer 4 — `examples/find_artist.py` updates

The existing pre-enrichment script (MusicBrainz-first, Discogs-,
iTunes-, Bandcamp-HTML-crawl fallbacks, no paid APIs) should grow:

- **New `--seed` source types:** TikTok (`@handle`), Tidal
  (`https://tidal.com/artist/{id}`), Facebook
  (`https://facebook.com/{handle}`), IPI number (numeric).
- **Two-source helper:** `python3 find_artist.py --name "Skee Mask"
  --disco-seed "..." --spotify-seed "..." --two-source-report` —
  outputs a `verification_report.json` showing which two-source pairs
  have matching artist names, scoring each pair.
- **DISCO mode:** `python3 find_artist.py --disco-mode --name "Skee
  Mask" --subdomain "skeemask"` — produces the exact JSON shape DISCO's
  signup step 5 expects (`verification_source_1`, `verification_handle_1`,
  `verification_source_2`, `verification_handle_2`).

### Out of scope for v0.3.4 (deferred)

- EAS attestations → separate `provenance-attestations` repo
- Spotify OAuth client_credentials refresh (current: user-supplied
  token in `set_api_keys`)
- Apple Music JWT flow for track-level metadata
- Discogs / Bandcamp / SoundCloud paid APIs
- Personal-website deep scraping
- Farcaster Hub integration via Neynar
- ENS text records (kept as Tier 6 placeholder; v0.3.5)

## Process

Layer 0 ships first (10-line Apple Music fix, no schema change).
Layer 1 (new Evidence fields + scoring) is the bulk of v0.3.4. Layers
2-4 build on Layer 1. Each layer is one commit. Pre-commit pipeline
(`ruff check` + AST + diff eyeball) before each commit. Push only on
explicit "push" from the user.

## Open decisions before Layer 1 starts

1. **Score cap.** Layer 1 adds 23 points (15 + 8) of new weights but
   rebalances Tier 2 to free 7 points. Net +16 over the 100 cap.
   Options: (a) rebalance Tier 1 too (reduce Spotify / Apple Music by
   ~16 total), (b) extend the cap to 115 and let LLM do more
   adjustment, (c) cap Layer 1's new weights at 50 points combined
   (so worst-case scoring stays bounded). Recommended: (a) — keep
   the 100 deterministic cap, rebalance Tier 1 modestly.
2. **Source enum storage.** Store as `str` (e.g. `"instagram"`) or
   as `u256` enum index? Recommended: `str` for readability in the
   on-chain Evidence dump; the storage cost difference is negligible.
3. **IPI checksum.** Worth implementing in v0.3.4, or punt to
   v0.3.5? Recommended: implement in v0.3.4 (10 lines, no new
   dependencies, useful signal even without per-PRO lookups).

## References

- DISCO signup page: `https://accounts.disco.ac/signup`
- DISCO API docs: `https://disco.readme.io/reference/authentication`
- DISCO app bundle: `https://static.disco.ac/disco-app/app-*.min.js`
  (current `app-e317412d8e459ca6.min.js`, 3.7 MB)
- CISAC IPI spec: ISO 7172 / CISAC IPI database (open to members)
- PRO public search endpoints (per-PRO, no unified public API):
  ASCAP, BMI, GEMA, PRS, SACEM, SIAE, JASRAC, APRA, SOCAN, etc.
