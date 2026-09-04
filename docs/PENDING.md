# v0.3.3 — Pending work

This document tracks the work that needs to land before the contract is
usable on testnet for real artist registrations. Items are ordered by
expected impact on verification correctness.

## Required before testnet deploy

### 1. Explicit `Evidence.to_dict()` for validator calldata round-trip

**Where:** `contracts/ProvenanceRegistry.py:808-841` (the
`_score_evidence_from_dict` function and the implicit `to_json` path
in `Evidence.to_json`).

**Risk:** The leader's `Evidence` return is serialized by GenVM into
`gl.vm.Return.calldata` and the validator re-parses it. The current
`Evidence.to_json` does `json.dumps(self.__dict__)`, which will throw
on `DynArray` and `u256` values. If GenVM calls our `to_json` literally,
the validator rejects every leader return and every `register_artist`
fails.

**Fix:** Add an explicit `Evidence.to_dict()` that converts
`DynArray[T]` to `list` and `u256` to `int` before serialization. Have
the validator call `to_dict()` on both sides (or define a module-level
`_evidence_from_dict` that calls it). Keep `to_json` for the onchain
audit log where the human-readable form is fine.

**Estimated size:** 1 method + 1 helper. ~15 lines.

### 2. API key admin setter

**Where:** `contracts/ProvenanceRegistry.py` — `_acoustid_api_key`,
`_spotify_token`, `_lastfm_api_key`, `_etherscan_api_key` all return
`""` with no way to set them.

**Risk:** Without a key, every API returns 401/403. Every
`register_artist` returns `"Not verified (X)"` where X is whatever
the LLM can synthesize from empty evidence. Contract is undeployable
in any meaningful sense.

**Fix:** Add a `@gl.public.write` admin method that stores the four
keys in contract storage:

```python
@gl.public.write
def set_api_keys(
    self,
    acoustid_key: str,
    spotify_token: str,
    lastfm_key: str,
    etherscan_key: str,
) -> str:
    self.acoustid_key = acoustid_key
    self.spotify_token = spotify_token
    self.lastfm_key = lastfm_key
    self.etherscan_key = etherscan_key
    return "API keys set"
```

Add the four storage fields to the `ProvenanceRegistry` class. The
admin caller's wallet should be checked against a stored admin
address (set at deploy time). For testnet, an unguarded setter is
fine.

**Estimated size:** ~25 lines + storage field declarations.

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
