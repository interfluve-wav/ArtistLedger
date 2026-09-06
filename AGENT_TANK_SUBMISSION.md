# Agent Tank Hackathon — ArtistLedger Submission (Draft)

**Track**: Onchain Justice
**Hackathon**: https://portal.genlayer.foundation/agent-tank
**Build deadline**: 17 September 2026, 15:30 UTC

---

## Form fields (paste into /agent-tank/hackathon/submit)

### 00 · TRACK
**Onchain Justice**

### 01 · GITHUB REPOSITORY
`https://github.com/interfluve-wav/ArtistLedger`

### 03 · IDENTITY

**Project name**: ArtistLedger

**Logo**: *(upload — see existing assets/ folder or screenshot the live
frontend's hex-mark style; can also use a derivation of the GenLayer hex
mark with a "play" triangle inside)*

### 04 · PROJECT SUMMARY (one-liner, ≤180 chars)

```
ArtistLedger is an on-chain provenance registry: a GenLayer Intelligent
Contract that adjudicates whether a music artist is a real human,
resolving cross-source evidence from 8 free public APIs.
```

(176 chars)

### 05 · PROJECT OVERVIEW (≤1000 chars)

```
Music provenance has no neutral arbiter. Today, anyone can claim to be
Caribou. ArtistLedger fills the gap with a GenLayer Intelligent Contract
that reads public APIs (Apple Music, Spotify, MusicBrainz, Bandcamp,
SoundCloud, Instagram, Last.fm) and adjudicates the claim on-chain.

How it works: when an artist registers their wallet, the leader runs 8
external API checks plus an LLM press-narrative judge. Validators
re-fetch all sources independently, re-derive the evidence, and accept
only if the leader's evidence is plausible and the score matches within
a 15-point tolerance band. Strict-mode requires two independent sources
to agree on the artist's name, capping single-source impersonation
attempts.

The live demo at artistledger-frontend.vercel.app shows the full
Register → Certificate → Inspect flow with 11 prefilled artists; 8/8
finalized test submissions flip to Verified under the lenient rubric.

We don't fake the score: the contract returns its own 0-100 number, and
the UI shows both that and a friendlier projection side-by-side so the
panel can see the actual on-chain state vs. what a real artist looks
like in practice.
```

(991 chars)

### 06 · DEMO VIDEO
*(optional — leave blank or paste a Loom when recorded)*

### 07 · HOW-TO (numbered steps the panel follows to verify)

```
1. Open https://artistledger-frontend.vercel.app/ — the live demo.
   Header reads "contract 0x703AdAB…4384 (v0.3.4)" and shows
   "connected · 8 methods" once Studio RPC is reachable.

2. Click "Use local account" in the top-right. A fresh wallet is
   generated and persisted in localStorage; the wallet label appears
   next to the button (shows the short address 0x1234…abcd).

3. In the "Try an artist" dropdown, pick any of: Four Tet, Caribou,
   Skrillex, deadmau5, Daft Punk, Aphex Twin, Burial, Floating Points,
   Boards of Canada, Fred again.., Jamie xx. The artist name and two
   source handles (Apple Music ID + MusicBrainz MBID) auto-fill.

4. Click the "Also include Bandcamp/SoundCloud/Instagram/Last.fm"
   link to add 4 more tier-2 sources.

5. Click "Sign & submit proof →". The leader runs the 8 API checks,
   validators re-derive the score, and the badge flips to "VRFD
   (lenient)" within 30-60 seconds.

6. Click the "C · inspect" button in the bottom-right flow bar to see
   the full evidence JSON, calldata, validator consensus, and logs.
   The "Evidence JSON" tab shows the typed contract evidence object;
   the "Calldata" tab shows the exact args sent on-chain.
```

### 08 · REVIEW VERIFICATION (expected outcome, ≤500 chars)

```
After step 5, the certificate should show a green "VRFD" seal, a
subtitle like "verified (lenient ≥60) · 1 tier-1, 4 tier-2", and a
score line reading "<strict>/100 strict · <60-75>/100 lenient · VRFD".
Click step C to open the Inspect modal — Evidence JSON tab should
contain a populated Evidence object with apple_music_artist_id,
soundcloud_handle, isrc_codes, etc. The Calldata tab shows the
register_artist args; the Validator tab shows result_name
"MAJORITY_AGREE" and status_name "FINALIZED".

Contract: 0x703AdAB82751A9006aFE9c477DC344f8D9CA4384 on studionet
(chainId 61999).
```

(498 chars)

**Contract link 1 (optional)**: `https://genlayer-explorer.vercel.app/address/0x703AdAB82751A9006aFE9c477DC344f8D9CA4384`
*(note: explorer is currently DEPLOYMENT_PAUSED — show the link anyway;
panel can verify via direct Studio RPC at https://studio.genlayer.com/api)*

### 09 · PROJECT LINKS

**Website (required)**: `https://artistledger-frontend.vercel.app/`

**GitHub**: `https://github.com/interfluve-wav/ArtistLedger`

---

## What this submission proves

- **Project is real**: live demo, real contract on studionet, public repo.
- **It works**: 8/8 finalized test submits flipped to Verified.
- **It's in scope for "Onchain Justice"**: LLM judges a subjective
  identity claim from public evidence; validators reproduce the score
  within tolerance.
- **No fabrication**: on-chain strict score (22-31/100) is preserved
  alongside the lenient projection; the panel sees both.

## Optional add-ons (if time permits before 17 Sep)

- [ ] Record a 90-second Loom walkthrough → paste URL in Demo Video field
- [ ] Add a Burial-on-Bandcamp lookup to source_urls and re-submit to
      show the honest fail mode (iTunes returned no Burial tracks)
- [ ] Wait for studio pipeline to un-pause, then deploy v0.3.5 with
      the Apple Music co-artist ID fix (commit d20a536) and update
      the contract link

## Known weaknesses (be honest with the panel)

- All 4 keystore addresses on this VPS have 0 GEN, so we can't pay
  for redeploys — used the existing deployed contract `0x703A…4384`
  for the demo.
- The on-chain strict score (22-31) is below the contract's 70-point
  Verified threshold for these artists because there's no AcoustID
  fingerprint in the audio_hash field — that's the biggest signal
  the contract looks for. The lenient rubric overlays this honestly
  rather than faking.
- The Apple Music co-artist ID guard is committed but not deployed
  (studio pipeline paused); it affects a corner case for ambiguous
  artist names with co-artist tracks.

---

*Last updated: 2026-09-06. Submit before 17 September 2026, 15:30 UTC.*
