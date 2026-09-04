# OnChainProvenanceRegistry

A GenLayer Intelligent Contract that tracks real-world music releases with
provenance validated through LLM comparative consensus. The primitive answers
one question with cryptographic certainty: **is this audio track provably
human-made and unaltered?**

## Why

Streaming platforms and AI music generators are flooding the market with
synthetic tracks credited to real artists, ghost releases, and uncredited
samples. There is no onchain layer today that lets a streaming service, sync
licensor, or royalty distributor trust that a track is real before letting it
into a "human-made" playlist, a sync deal, or a royalty pool.

This contract is that layer.

## What it does

- **`register_artist`** — links a wallet to a real human identity by fetching
  evidence URLs (artist site, MusicBrainz entry, ISRC/ISWC records) and asking
  validators to cross-check identity via LLM comparative consensus
- **`anchor_release`** — once an artist is verified, they can anchor a release
  (audio hash + title + contributors + release date) onchain
- **`dispute`** — anyone can dispute a release with evidence (e.g., "this is
  AI-generated", "this samples my work without credit"). Validators judge the
  dispute; if it holds, the release is marked contested
- **`is_verified_human`** — read-only query: given an audio hash, returns
  whether the release is verified human-made and uncontested

## Consensus

Every state-changing method uses GenLayer's equivalence principle:

- **Identity verification** — `run_nondet_unsafe` with a leader/validator
  pair. Leader fetches evidence, LLM scores 0-100. Validators re-fetch
  sources, re-score independently, accept if within tolerance band (15).
- **Dispute resolution** — same pattern. Leader evaluates dispute evidence,
  validators re-evaluate, accept if consensus holds.
- **Anchor and view methods** — no consensus needed, deterministic.

The LLM never decides alone. The validator re-runs the judgment and
re-fetches the evidence. The leader's output is only accepted if a majority
of validators independently agree it satisfies the criteria.

## Use cases

- **Streaming platforms** — call `is_verified_human(audio_hash)` before
  ingesting a track into a "human-made" playlist
- **Sync licensing** — verify a track is by the credited artist before
  issuing a sync license
- **Royalty distribution** — gate a royalty pool on provenance verification
- **AI-music detection** — flag a release as contested when disputed

## Install / Test

This contract targets the GenLayer testnet. The `genlayer/write-contract`
skill in [internet-court/internet-court-skill](https://github.com/internet-court/internet-court-skill)
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
tests/
  test_provenance.py        Unit tests for state transitions
docs/
  ARCHITECTURE.md           Deep dive on the consensus logic
```

## License

MIT.
