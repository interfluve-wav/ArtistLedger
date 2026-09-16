# Architecture

ArtistLedger is a **GenLayer Intelligent Contract** — a GENVM Python
program — that adjudicates music-provenance claims. This document
describes the current design (v0.7.2).

## Position in the stack

GenLayer is the adjudication layer for the agentic-commerce stack:
machine-speed judgment when a transaction becomes ambiguous or
contested. ArtistLedger is a domain-specific **Trustless World
Database** for music artist identity and release provenance — the
verification & disputes primitive for music.

## Consensus model

GenLayer runs **Optimistic Democracy**: a leader proposes an execution,
validators vote, majority wins. Our contract applies that to
*real-world evidence*:

1. **Leader phase** — on `register_artist`, the leader runs the 8 API
   checks (Apple Music, Spotify, MusicBrainz, Bandcamp, SoundCloud,
   Instagram, Last.fm, Etherscan) plus an LLM press-narrative judge,
   and builds a typed `Evidence` object.
2. **Validator phase** — validators **deterministically audit the
   evidence**: they re-score the exact evidence the leader submitted,
   verify each claimed source against the source rules, and check the
   proof tokens. There is **no live re-fetch** — validators work from
   the same frozen evidence, so consensus cannot drift on API rate
   limits or timestamp differences.
3. **Verdict** — a majority agree → `MAJORITY_AGREE` / `FINALIZED`;
   the certificate flips to **VRFD** when the score clears the
   threshold. If a majority disagree, the registration is rejected
   (floor rejection) rather than silently accepted.

## Scoring

- Strict on-chain score, 0–100. The strongest signal is an
  **ALVERIFY proof token** (+25 each) pasted into the artist's own
  profile bios: `ALVERIFY:<FNV1a(wallet.lower + ":" + name.lower)>`,
  30-char alphabet, exact grep on the bio text. Tokens are
  single-use — a token already bound on-chain is refused, so the
  token sitting in a public bio cannot be replayed.
- **Strict mode** (default) requires **two independent sources** to
  agree on the artist name; with fewer, the strict score is capped.
- The frontend shows the strict score **and** a lenient projection
  side by side — an honest dual score, nothing faked.

## Identity

- `register_artist` binds a wallet to a real artist identity via the
  profile cluster (the API evidence).
- `reverify` rotates a verified identity to a **new wallet** when the
  artist re-proves control of the same profiles with a fresh token:
  the old wallet is revoked on-chain, releases and indexes re-point
  to the new key, and a hijacker who can't show a token on a profile
  from the original evidence is rejected. Lost key = recover; stolen
  key = revoked.
- Artists without a catalog (no releases found) hit a validator floor
  and are rejected rather than egressing as variance.

## Contract surface (15 methods)

| Method | Purpose |
|---|---|
| `register_artist` | adjudicate a claim, emit certificate |
| `reverify` | rotate identity to a new wallet |
| `anchor_release` | anchor a release (audio hash + credits) |
| `dispute` | contest a release with evidence |
| `is_verified_human` | query: verified + uncontested? |
| `get_artist` / `get_release` / `get_dispute` | read state |
| `get_verified_by_token` / `get_verified_by_name` | lookups |
| `set_api_keys` / `set_lastfm_key_pool` / `set_spotify_key_pool` | operator key pools |
| `get_lastfm_pool_size` / `get_spotify_pool_size` | pool health |

## State

User-facing maps (`artists`, `releases`, `disputes`) plus internal
counters that prevent gaming (`identity_score`, `identity_count`,
`artist_releases`). Every `Artist` stores its JSON-serialized
`Evidence`, so any observer can read on-chain exactly which factors
contributed to a verification — auditable by construction.

## What this contract is NOT

- **Not a legal proof of ownership** — the on-chain record is
  evidence, not a copyright registration.
- **Not a copyright enforcement system** — a dispute marks a release
  contested; it doesn't delete anything.
- **Not a substitute for platform moderation** — one signal, not the
  only signal.
- **Not a 100% guarantee against AI music** — a well-resourced
  attacker who controls many verification APIs can raise the
  deterministic score; the contract raises the *cost* of faking
  provenance rather than eliminating the possibility.

## API dependencies

All free, all public, no paid keys for the structural flows
(AcoustID/Last.fm/Etherscan use free-tier keys, pool-managed in
contract state via the `set_*_key_pool` methods; MusicBrainz requires
only a UA string).

## See also

- [README](../README.md) — pitch, demo, quickstart
- [QUICKSTART](QUICKSTART.md) — run, test, verify on-chain
