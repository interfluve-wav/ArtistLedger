# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (v0.3.3)

- **`Evidence.to_json` would throw on `DynArray` and `u256` values** because
  `json.dumps(self.__dict__)` is not JSON-native for those types. Added
  an explicit `Evidence.to_dict()` that converts `DynArray` to `list`
  and `u256` to `int`, and have `to_json` route through it. The
  validator's `json.loads(leader_result.calldata)` path now works
  for any JSON-string wire format.
- **API key accessors returned `""` with no way to configure them.**
  Added four storage fields on `ProvenanceRegistry`
  (`acoustid_key`, `spotify_token`, `lastfm_key`, `etherscan_key`) and
  a `@gl.public.write set_api_keys(...)` admin method. The four
  module-level API helpers (`_acoustid_lookup`, `_spotify_search`,
  `_lastfm_scrobbles`, `_wallet_age_days`) now take their key as a
  parameter; `register_artist.leader_collect` reads the keys from
  contract storage once at the top and threads them through. The
  dead module-level `_acoustid_api_key` / `_spotify_token` /
  `_lastfm_api_key` / `_etherscan_api_key` functions have been
  removed.

### Added (v0.3.4 Layer 0 + Layer 1)

- **Apple Music `limit=1` fix (Layer 0).** `_apple_music_search` now
  queries `entity=musicTrack&limit=5` and sets `track_present` only
  when a track's `artistName` contains the claimed artist name
  (co-artist guard). `W_APPLE_MUSIC` is now actually awardable.
- **Two-source verification (Layer 1, DISCO signup parity).** New
  `Evidence` fields `verification_source_1/2`, `verification_handle_1/2`
  (str) and `verification_match_count` (u256). `register_artist` takes
  four optional args (defaults `""` for backward compat). New
  `_verify_claimed_source` dispatches on the DISCO 13-enum source type,
  resolving Spotify/Apple/Bandcamp/SoundCloud/Instagram through the
  existing collectors; claim-only sources (TikTok/Tidal/FB/website/
  Twitter/YouTube) return `False` pending Layer 2. Scoring awards
  `W_TWO_SOURCE_MATCH` (15) for 2 matches, `W_SINGLE_SOURCE_MATCH` (8)
  for 1. Tier-2 rebalanced (bandcamp 5→3, soundcloud 5→3, instagram
  5→2, lastfm 5→2) to hold the 100 deterministic cap.
- **Two-source verification hardens (Layer 2).** `_verify_claimed_source`
  no longer returns claim-only `False` for most platforms — added real
  checks: IPI CISAC mod-101 checksum, TikTok profile-name scrape (embedded
  JSON), Tidal + Facebook HTTP existence, personal-website name mention.
  SoundCloud/Instagram stay existence-only (private APIs; documented).
  Twitter/YouTube remain claim-only pending API keys.
- **Strict two-source mode (Layer 3).** `register_artist` now takes a
  `require_two_source: bool = True` argument. When True and fewer than two
  claimed sources independently match, the score is capped at 5 — below
  the 70 threshold — so registration is rejected at consensus. Set False
  to opt into relaxed single-source onboarding.
- **`find_artist.py` DISCO glue (Layer 4).** Two new flags:
  `--disco-mode` emits the DISCO step-5 shape (all 13 enum types ->
  `{url, handle, found}`) and `--two-source-report` picks the two
  strongest discovered sources as ready-to-paste
  `verification_source_1/2` args for `register_artist()`. Live-tested:
  Burial resolves to apple_music + bandcamp. Also added repo-wide ruff
  config (per-file BLE001/S110 ignore for examples/, fail-quiet by design).

### Known issues (still open)

- **Farcaster endpoint.** The contract calls
  `https://api.farcaster.xyz/v2/user-by-cast-address` which is not a
  public Farcaster Hub path. Real Hub endpoints are on
  `hub.farcaster.xyz:2281` with a gRPC-style request shape. Field
  currently returns `""` for every wallet.
- **Apple Music `limit=1` (not `wrapperType`).** The iTunes Search
  URL was `?entity=musicArtist,musicTrack&limit=1` — with `name`
  it returned the artist only, so `track_present` stayed `False`
  and `W_APPLE_MUSIC` was never awarded. **Fixed in v0.3.4 (Layer 0):**
  `entity=musicTrack&limit=5` + a `name in artistName` co-artist guard.
- **Spotify `verified` flag.** The public Spotify Web API search
  endpoint does not return a `verified` boolean on artist objects. The
  scoring branch `ev.spotify_verified or (popularity >= 20 AND
  followers >= 1000)` will fall back to the popularity/follower check
  for every real artist, which works but under-credits actually
  verified accounts.
- **Bandcamp / SoundCloud / Instagram HTML scraping.** These are not
  APIs. They will break the moment any of these sites change their
  HTML structure. The contract parses bio/location/follower fields
  out of the page body, which is fragile.
- **Docstring headers** in `contracts/ProvenanceRegistry.py` (line 3)
  and `tests/test_provenance.py` (line 2) still say `v0.2.0`. Cosmetic
  but visible to reviewers.

## [0.3.3] - 2026-09-04

See the [Unreleased](#unreleased) section above for the two fixes in
this release: `Evidence.to_dict()` for validator calldata round-trip
and the `set_api_keys` admin method.

## [0.3.2] - 2026-09-04

### Changed

- `contracts/ProvenanceRegistry.py`: file-level
  `# ruff: noqa: BLE001,S110` with rationale. Every `except Exception:`
  in the contract is a fail-soft API call wrapper; narrowing each one
  to `(json.JSONDecodeError, KeyError, ValueError, ...)` gains little
  for the consensus-critical surface and clutters the code. `S110`
  (try-except-pass) is the inner try in `_acoustid_lookup` where any
  failure means "no match".
- Flattened the nested `if ev.spotify_artist_id: if ev.spotify_verified
  or (...):` in `_score_evidence` into a single boolean expression,
  preserving the `spotify_artist_id` guard.

### Removed

- Dead `mb_artist = _musicbrainz_artist(name); if mb_artist: pass` block
  in `register_artist.leader_collect`. The result was unused. The
  `_musicbrainz_artist` helper is now unreferenced; kept for now
  because the call site is in a `run_nondet_unsafe` leader function
  and may be useful for future cross-validation.
- Unused `W_APPLE_MUSIC` import from `tests/test_provenance.py`.
- Unused `timezone` import from `contracts/ProvenanceRegistry.py`.

## [0.3.1] - 2026-09-04

### Fixed

- **`_wallet_age_days` returned `first_tx_ts // 86400` (≈ 20,000 for
  any real wallet), not actual wallet age.** The 90-day threshold in
  `_score_evidence` was always trivially passed. Now returns
  `(now - first_tx_ts) // 86400` with a `now <= ts` guard that returns
  0 for clock-skew or freshly-funded wallets. The dead
  `_approx_days_from_unix` helper has been removed.
- **`_now()` used `datetime.now(timezone.utc)`.** Switched to
  `datetime.fromisoformat(gl.message_raw['datetime']).timestamp()`.
  Same value across validators per `docs.genlayer.com` transaction-
  context, and unambiguous regardless of `run_nondet_unsafe` block
  placement.
- **`class Evidence(gl.Contract)`** violated the documented
  storage-class contract. Switched to `@allow_storage @dataclass
  class Evidence:` per GenLayer v0.2.9 docs (storage structs use
  `@allow_storage @dataclass`, not `gl.Contract` inheritance).

## [0.3.0] - 2026-09-04

### Changed

Aligned the contract with the GenLayer SDK v0.2.9 API surface.
Previously the contract used names from the older genlayer-py
naming (`msg.sender`, `block.timestamp`, `bytes32`, `u64`, `list[T]`)
that the v0.2.9 SDK no longer accepts. Replaced with:

- `msg.sender` → `gl.message.sender_address`
- `block.timestamp` → `gl.message_raw['datetime']` (consensus-safe
  transaction time; see v0.3.1 follow-up for where this is now
  sourced)
- `bytes32` → `bytes`
- `u64` → `u256`
- `list[Address]` → `DynArray[Address]`
- `list[str]` → `DynArray[str]`

Added `_sender()` and `_now()` helpers on the contract for
testability; tests were rewritten to patch those instead of
class-level `msg` and `block` attributes. `u256` wrapping at all
storage write sites, `int()` casts at read sites.

### Known limitations at the time of release

- Tests syntax-checked but not executed (py-genlayer not pip-
  installable on the development host).
- The contract has never been deployed to testnet. The
  `_score_evidence_from_dict` path (validator receiving leader's
  calldata) and the API response shapes for Spotify/Apple Music/
  Bandcamp/SoundCloud/Instagram are best-guesses from public
  documentation.

## [0.2.1] - 2026-09-04

### Added

- Positioned the contract in the GenLayer Compass stack and added
  the `examples/integration_x402.py` pseudocode for using
  `is_verified_human` as a payment gate in an x402 buyer flow.

## [0.2.0] - 2026-09-04

### Changed

- Replaced the v0.1.0 LLM-only judge with a structured-evidence
  approach: 13 fields across 8+ public APIs scored deterministically
  (0-95 points) plus a bounded LLM qualitative adjustment (±5 points).
- Added the asymmetric dispute threshold (60 uphold vs 70 verify) so
  that a single piece of strong contrary evidence can flip a release
  to contested.

## [0.1.0] - 2026-09-04

### Added

- Initial commit. OnChainProvenanceRegistry v0.1.0 with the naive
  pure-LLM judge for music artist verification. Superseded by v0.2.0.
