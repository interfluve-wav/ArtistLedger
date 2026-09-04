# Architecture

## Why structured evidence + LLM adjustment, not a pure LLM judge

The naive approach (v0.1.0) was: pass the LLM a free-form prompt asking it
to score "is this artist real?" from 0-100. That's a vibe check. It has
three problems:

1. **Unauditable.** Nobody can read the contract and know which factors
   matter. The score is whatever the LLM felt like.
2. **Non-deterministic.** Same evidence, different scores across nodes
   and time. Hard to reason about a "70" threshold.
3. **Easy to game.** A sophisticated attacker can craft a prompt that
   elicits a high score from the LLM, with no underlying truth.

v0.2.0 replaces the single LLM judge with a **two-layer system**:

### Layer 1: deterministic evidence collection (95 points max)

A `collect_evidence` function hits 8+ free public APIs and extracts
**13 structured fields** into an `Evidence` dataclass. Each field is
a deterministic extract from a real API response — no LLM in the loop.

The fields, grouped by tier:

| Tier | Field | Source | Weight |
|---|---|---|---|
| 1 | acoustid_matched | AcoustID lookup | 20 |
| 1 | isrc_codes | MusicBrainz | 10 |
| 1 | spotify_artist_id | Spotify Web API | 10 |
| 1 | apple_music_track_present | Apple iTunes | 5 |
| 2 | bandcamp_handle | Bandcamp | 5 |
| 2 | soundcloud_handle (verified OR ≥100 followers) | SoundCloud | 5 |
| 2 | instagram_handle | Instagram | 5 |
| 2 | lastfm_scrobble_count ≥100 | Last.fm | 5 |
| 5 | wallet_age_days ≥90 | Etherscan | 5 |
| 5 | ens_name matches OR farcaster_fname | ENS / Farcaster | 5 |

**Sum of deterministic weights: 95 points.**

A fabricated identity with no cross-source corroboration gets 0. A real
artist with even minimal web presence (AcoustID + Spotify + MusicBrainz)
gets 20-30. Threshold is 70 — high enough that it requires real cross-source
verification, low enough that underground/indie artists can pass.

### Layer 2: LLM qualitative adjustment (±5 points)

A small LLM call evaluates the **narrative consistency** of the
collected evidence: do the sources tell a coherent biographical story,
or do they describe unrelated people/events? The output is bounded to
[-5, +5] and added to the deterministic score.

**This is the only LLM in the verification path, and it can move the
score by at most 5 points.** A real artist's score is dominated by the
deterministic factors; a fabricated identity cannot reach 70 by gaming
the LLM alone.

## Why two tolerance-band validators over strict_eq

`gl.eq_principle.strict_eq` requires all nodes to return *exactly* the
same value. That works for fetching a block height from a single API.
It does NOT work for two cases here:

1. **Multi-API aggregation** — different nodes may hit the APIs at
   slightly different times, getting different rate-limit responses,
   different MusicBrainz revision timestamps, etc.
2. **LLM qualitative judgment** — the same prompt can return 3 on one
   node and 4 on another for legitimate reasons (model temperature,
   context length differences).

So we use `run_nondet_unsafe` with a custom `validator_fn` that
**re-derives the evidence independently** and accepts if both:

- The re-derived `Evidence` struct agrees with the leader's on the
  boolean flags that gate score components
- The independently-computed score is within ±15 of the leader's score

The ±15 tolerance is wide enough to absorb API timestamp drift and
LLM variance, narrow enough that a wildly wrong validator (one that
returns 30 while the leader returns 80) is rejected.

## Why 70 for verification, 60 for disputes

**Verification threshold: 70.** A score below 70 means the evidence is
too sparse to confidently claim a real identity. Real artists with
even minimal web presence (one music platform, one social profile)
should clear this. Fabricated identities with no cross-source
corroboration cannot.

**Dispute uphold threshold: 60.** Lower than verification because the
burden of proof is asymmetric: a real artist should be able to register
with modest evidence, but it should be easier to challenge a release
than to defend one. 60 (vs 70) means a single piece of credible
contrary evidence (e.g., a sample-match showing the audio was
Suno-generated) is enough to flip the release to contested.

**Tolerance band: 15.** A 15-point spread on a 0-100 score is wide
enough to absorb LLM variance, narrow enough that a validator wildly
over-estimating or under-estimating the leader's claim gets rejected.

These three numbers are the only knobs in the contract. If they're
wrong, they can be tuned in a v2 — but the shape (multi-source fetch,
comparative consensus, asymmetric burden) is the load-bearing part.

## Why we re-fetch the same APIs for every validator

A naive validator would just call the LLM with the leader's output and
ask "is this reasonable?" That's a security hole: the validator is
asking the LLM to trust the leader's framing. The LLM has no way to
know if the leader's evidence is real or fabricated.

So the validator re-fetches each API from scratch. This costs more
(consensus time, validator bandwidth) but it's the only way to get
non-circular validation. The leader's job is to propose; the
validator's job is to independently verify the proposal by re-running
the experiment from the same inputs.

## State

Six maps. Three are user-facing (`artists`, `releases`, `disputes`);
three are internal counters that prevent gaming:

- `identity_score` — the *last* consensus score for a wallet. A failed
  attempt still updates this so a wallet can't keep retrying with the
  same bad evidence.
- `identity_count` — how many times the wallet has tried to register.
  Useful for rate-limiting future work.
- `artist_releases` — index of audio hashes per artist. Cheap to fetch
  "all releases by artist X" without scanning the entire `releases` map.

The `Artist.evidence` field stores the JSON-serialized `Evidence`
struct, so any observer can read onchain *exactly* which factors
contributed to a verification. Auditable.

## What this contract is NOT

- **Not a legal proof of ownership.** The onchain record is evidence,
  not a substitute for a copyright registration. A real legal dispute
  still needs a court.
- **Not a copyright enforcement system.** Filing a dispute does not
  delete the release. It marks it as contested, which downstream
  services can act on, but the contract has no view of off-chain
  music distribution.
- **Not a substitute for platform moderation.** A streaming platform
  should still do its own checks; this contract is one signal, not
  the only signal.
- **Not anonymous.** The `register_artist` method links a wallet to a
  real-world identity. Artists who want to remain pseudonymous can do
  so (use a stage name, link to a DID that doesn't reveal legal name),
  but the *wallet* is permanently tied to the verification evidence.
- **Not a 100% guarantee against AI music.** A sufficiently
  well-resourced attacker who controls many of the verification APIs
  (e.g., creates fake SoundCloud + Bandcamp + Instagram profiles with
  cross-links) can pass the deterministic threshold. The LLM
  qualitative judgment is the catch — but it's only ±5 points. The
  contract is best understood as raising the *cost* of faking
  provenance, not eliminating the possibility.

## API dependencies

All free, all public, no paid keys required for the structural flows.
Some have rate limits:

| API | Auth | Rate limit |
|---|---|---|
| AcoustID | API key (free) | 3 req/sec |
| MusicBrainz | None (UA required) | 1 req/sec |
| Spotify | OAuth client_credentials | generous |
| iTunes | None | unrestricted |
| Bandcamp | None | unrestricted |
| SoundCloud | None | unrestricted |
| Instagram | None (oEmbed) | soft |
| Last.fm | API key (free) | 5 req/sec |
| ENS | None | generous |
| Etherscan | Free API key | 5 req/sec |
| Farcaster | None | generous |

In production, the contract would initialize with these API keys
stored as contract state, set once at deploy time.
