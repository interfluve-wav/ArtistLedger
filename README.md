# OnChainProvenanceRegistry

A GenLayer Intelligent Contract that tracks real-world music releases with
provenance validated through structured cross-source verification and
bounded LLM qualitative adjustment. The primitive answers one question
with cryptographic certainty: **is this audio track provably human-made
and unaltered?**

## Why GenLayer, why now

From the [GenLayer Compass](https://portal.genlayer.foundation/genesis/compass):

> Every layer [of the agentic-commerce stack] assumes the happy path.
> None handles the moment something goes wrong. That missing piece is
> adjudication.

> Read the specifications of the agentic-commerce stack as it is being
> released right now. x402 has no formal dispute mechanism. ERC-8004:
> adjudication is managed by specific validation protocols. A2A: dispute
> resolution is not defined within the protocol.

> GenLayer is the adjudication layer for the agentic-commerce stack:
> machine-speed judgment when a transaction becomes ambiguous or
> contested.

The [GenLayer whitepaper](https://www.genlayer.com/whitepaper) describes
the consensus mechanism as **Optimistic Democracy** — a leader proposes
a transaction execution, validators vote, majority wins — and lists
**Trustless World Database** as a primary use case. This contract is a
domain-specific Trustless World Database for music artist identity and
release provenance.

It also slots directly into the stack at layer 06 (Verification &
disputes), alongside Kleros and UMA, and is designed to be called by
x402 payment flows to gate transactions on `is_verified_human`.

## What it does

- **`register_artist`** — links a wallet to a real human identity by
  collecting 13 structured evidence fields from 8+ free public APIs
  (AcoustID, MusicBrainz, Spotify, Apple Music, Bandcamp, SoundCloud,
  Instagram, Last.fm, ENS, Etherscan, Farcaster), computing a
  deterministic score, and applying a bounded LLM qualitative
  adjustment
- **`anchor_release`** — once an artist is verified, they can anchor a
  release (audio hash + title + contributors + release date) onchain
- **`dispute`** — anyone can dispute a release with evidence (e.g.,
  "this is AI-generated", "this samples my work without credit").
  Validators judge the dispute via LLM comparative consensus; if the
  dispute is upheld, the release is marked contested and the artist's
  reputation is penalized
- **`is_verified_human`** — read-only query: given an audio hash,
  returns whether the release is verified human-made and uncontested

## Consensus

Every state-changing method uses GenLayer's equivalence principle
executed under Optimistic Democracy:

- **Identity verification** — `run_nondet_unsafe` with a custom
  leader/validator pair. The leader collects evidence, scores it
  deterministically (95 pts max) plus a bounded LLM adjustment
  (±5 pts). The validator **re-fetches every API independently**,
  re-derives the evidence, and accepts only if the re-derived score
  is within a 15-point tolerance band.
- **Dispute resolution** — same pattern. Leader evaluates dispute
  evidence, validators re-evaluate, accept if consensus holds.
- **Anchor and view methods** — no consensus needed, deterministic
  state transitions.

The LLM never decides alone. The leader's output is only accepted if
a majority of validators independently re-derive the same answer from
the same inputs.

## Use cases

- **Streaming platforms** — call `is_verified_human(audio_hash)` before
  ingesting a track into a "human-made" playlist
- **Sync licensing** — verify a track is by the credited artist before
  issuing a sync license
- **Royalty distribution** — gate a royalty pool on provenance
  verification
- **x402 payment flows** — gate a payment on the seller's catalog
  being verified human
- **AI-music detection** — flag a release as contested when disputed

## Integration example (x402 + Internet Court)

A payment flow can call this contract to gate a transaction on
provenance. From `examples/integration_x402.py`:

```python
# Pseudocode for an x402 buyer that gates payment on provenance
def purchase(track, payment):
    audio_hash = track.audio_hash
    if provenance.is_verified_human(audio_hash):
        release = provenance.get_release(audio_hash)
        if release["artist"] == track.claimed_artist:
            return payment.execute(track.seller, track.price)
        else:
            raise ArtistMismatchError(track.claimed_artist, release["artist"])
    else:
        # Don't pay for unverified tracks; let buyer decide
        raise UnverifiedProvenanceError(audio_hash)
```

The same pattern applies to Internet Court's verification & disputes
layer: an Internet Court contract that handles agent-to-agent
deliverables can call this contract's `is_verified_human` and
`get_dispute` methods to check whether a disputed deliverable is a
real-world human-made music release or contested.

## Install / Test

This contract targets the GenLayer testnet. The
`genlayer/write-contract` skill in
[internet-court/internet-court-skill](https://github.com/internet-court/internet-court-skill)
ships the test runner. Standard usage:

```bash
# Deploy to testnet
genlayer deploy contracts/ProvenanceRegistry.py --network testnet

# Run the example end-to-end script
python examples/verify_and_anchor.py
```

## Repo layout

```
contracts/
  ProvenanceRegistry.py     The Intelligent Contract
examples/
  verify_and_anchor.py     End-to-end demo (register → anchor → query)
  integration_x402.py      Pseudocode for x402 / Internet Court
tests/
  test_provenance.py        Unit tests for state transitions
docs/
  ARCHITECTURE.md           Deep dive on the consensus logic
```

## License

MIT.
