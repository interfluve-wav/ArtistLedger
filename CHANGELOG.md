# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Known issues (documented, not yet fixed)

- **API key accessors all return `""`.** `_acoustid_api_key`,
  `_spotify_token`, `_etherscan_api_key`, `_lastfm_api_key` have no
  initializer or setter exposed on the contract. Every real-artist
  `register_artist` call will currently fail verification because
  AcoustID, Spotify, and Etherscan will return 401/403. Needs a
  `@gl.public.write` admin setter or a deployment-time env-reader before
  the contract is usable on testnet.
- **Docstring headers** in `contracts/ProvenanceRegistry.py` (line 3)
  and `tests/test_provenance.py` (line 2) still say `v0.2.0`. Cosmetic
  but visible to reviewers.
- **Farcaster endpoint.** The contract calls
  `https://api.farcaster.xyz/v2/user-by-cast-address` which is not a
  public Farcaster Hub path. Real Hub endpoints are on
  `hub.farcaster.xyz:2281` with a gRPC-style request shape. Field
  currently returns `""` for every wallet.
- **Apple Music `wrapperType` field.** The iTunes Search API does not
  return `wrapperType`; that's from the newer Apple Music API which
  requires a developer JWT. The current parser will not match any
  iTunes Search response. Drop the field or implement the JWT flow.
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
- **`Evidence` serialization through `run_nondet_unsafe`.** The leader
  returns an `Evidence` dataclass from inside `run_nondet_unsafe`;
  the validator receives the result as `gl.vm.Return.calldata` and
  re-parses it via `_score_evidence_from_dict`. Whether GenVM
  serializes `@allow_storage @dataclass` instances through
  `to_json(self.__dict__)` (which will throw on `DynArray` and `u256`)
  or via a structured wire format is undocumented in the v0.2.9 SDK
  reference and only verifiable on a live testnet deploy.

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
