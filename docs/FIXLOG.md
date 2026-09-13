# Fix Log — 2026-09-13 (hackathon prep)

Running log of fixes while preparing the Agent Tank submission.
Each entry: what was broken, root cause, what changed, how verified.
Latest at the bottom.

---

## 2026-09-13 — Live-data fixes (Spotify + Last.fm)

### F1. Spotify followers/popularity dead after Feb-2026 API change
**Symptom:** live test with the app's own client credentials returned
`followers=None`, `popularity=None` for every artist (even Beyoncé).
The contract's `W_SPOTIFY` branch could never fire.
**Root cause:** Spotify's February 2026 Web API changelog REMOVED the
`followers` and `popularity` fields from artist responses for all
development-mode apps. March 2026 postponed endpoint cuts for existing
integrations but the field removals stand. Only Extended Quota mode
receives them. Verified via changelog + live API response shape.
**Fix:**
- New evidence field `spotify_name_matched: bool` — set when the top
  search hit's name token-overlaps the claimed name ≥ 0.5.
- `_spotify_search` tags the top result with `_name_matched`.
- Scoring: `W_SPOTIFY` now fires on `verified OR name_matched OR
  (popularity≥20 AND followers≥1000)` — the last kept for quota keys.
- Validator guard changed: `spotify_verified` requires an artist id
  (previously required followers>0 — a field that no longer exists, so
  legit verified artists would have been rejected).
**Verified:** live test with app creds — Four Tet ✓, Burial ✓,
Fred again.. ✓ (.. quirk survives), fake name → no result → no signal;
fields confirmed absent from dev-mode responses; 120 tests green.

### F2. Last.fm profile scrape read the wrong number
**Symptom:** `_lastfm_profile_and_scrobbles` returned 17 for profile
RJ — a brand-new sybil account would pass the 200-scrobble maturity
floor on a lie.
**Root cause:** the regex `([\d,]+)\s*scrobbles?` matched the page's
average-per-day TOOLTIP («an average of 17 scrobbles per day!»), not
the lifetime count (151,481).
**Fix:** anchor on the `Scrobbles` header + the `/user/{handle}/library`
link: `header-metadata-title"> Scrobbles </h4>…library"> 151,481</a>`.
Verified against a real 456KB page capture; saved as the regression
fixture `tests/fixtures/lastfm_profile_rj.html`. Interstitial pages
fail safe → 0 (no false maturity).
**Also:** Last.fm serves an intermittent «Temporarily Unavailable»
interstitial (bot defense) — the reader treats it as 0. UA-browser
headers get through when tested from curl; GenVM fetch may need the
same UA if this persists.

### F3. Last.fm artist.getInfo requires the canonical name
**Symptom:** a user typing «fred again..» got 0 userplaycount even for
a genuine fan account.
**Fix:** new `_lastfm_resolve_artist()` — resolves the claimed name via
`artist.search`, requires an MBID (rejects vanity/unregistered pages),
feeds the canonical name into `artist.getInfo`. Keyless → no signal.
5 tests (canonical resolution, no-key, no-MBID, no-matches,
search-then-getInfo call order).

---

## 2026-09-12 — infra + feature work (see git log for detail)

- `6ccac62` ci: watcher hard-resets working tree to origin/main before
  deploy (was deploying whatever sat in the VPS working tree — stale
  code could ship while the SHA marker claimed otherwise).
- `ff30fc8` feat: ownership proofs — ALVERIFY artist-controlled tokens
  (SoundCloud bio / Last.fm profile / Bandcamp about / YouTube
  description), +12/channel capped at 2, Last.fm 200-scrobble maturity
  floor + validator fabrication guard. Later split to
  `feat/ownership-proofs` per user request, then cherry-picked back.
- `210e9a7` feat: artist portrait on VRFD certificate (Wikipedia REST,
  keyless, disambiguation-guarded).
- `7b811a7` dark operator console re-skin (GenLayer aesthetic, reactive
  globe driven by app.js DOM signals via MutationObserver — zero
  app.js changes).
### F4. Spotify client-credentials mint (no OAuth needed)
**Symptom:** contract took one long-lived `spotify_token`; frontend had no
OAuth flow, so the Spotify tier was dead without a manually-minted bearer.
**Fix:** `_spotify_mint_token(client_id, client_secret)` — client-credentials
flow (no user consent). `leader_collect` falls back to minting when the stored
token is empty and client creds exist. `set_api_keys` gained two optional
trailing args (defaults `""` — no ABI break).
**Verified:** live mint + search for Four Tet with real creds (id returned,
followers/popularity absent per F1 — name-binding carries the tier-1 signal).
**Tests:** 123 green (3 new: mint fallback, creds storage, bad-creds → "").
**Keys:** `.env` now has SPOTIFY_CLIENT_ID/SECRET (your own app), chmod 600,
gitignored; only key NAMES ever logged.
