# Variant 010 — Unified flow (register → settle → inspect)

## Design stance

The full user journey in one page, in three explicit states.

- **State A — register** (the 003 split-pane: form on left, live
  cross-reference on right, animated pulse on the resolving sources)
- **State B — certificate** (the 008 minimal cert: paper aesthetic,
  10 expandable evidence rows, the full score breakdown with
  subtotal/total)
- **State C — inspect** (the 005 modal: 4-tab raw evidence view, the
  full calldata, validator run, and timestamped logs)

A single block of JS handles the three-state transition. A floating
flow controller at the bottom right lets the viewer skip to any state
without going through the natural progression. Pressing "reset" returns
to A.

## The transition

A → B: the split-pane fades out (0.6s opacity + 8px translate-down),
then the cert fades in (0.8s opacity + 8px translate-up, delayed 0.4s).
The block number in the header changes from `#1,884,221` to
`#1,884,229` to suggest "this is the same artist, different block."

B → C: the modal opens over the cert. No cert state change; the cert
is still visible behind a backdrop blur. Pressing Esc, clicking the
close button, or clicking the backdrop returns to B.

C → A: only via "reset" (sketch-only). In the real product, the user
would not return to A from C — they would have already moved on to
Anchor Release, View on Etherscan, etc.

## What's in the cert (state B)

All 10 expandable evidence rows: 2 from two-source verification
(Spotify, Bandcamp) and 8 from public-data cross-reference (Spotify,
Apple Music, Bandcamp, SoundCloud, Twitter, MusicBrainz, Discogs, IPI).
The 5 "not checked" rows (Instagram, YouTube, TikTok, Tidal, Facebook)
are visible in the cert text but not as expandable rows — they're
shown in the meta line "5 hit, 1 fail, 7 not checked."

The score breakdown reconciles: 89 deterministic + 5 LLM = 94
(verified by removing the redundant "Single-source match" line).

## What's in the modal (state C)

4 tabs, all the technical detail:

- **Evidence JSON** — the leader.run_nondet_unsafe output, with the
  full Evidence dataclass as JSON
- **Calldata** — the sha256 hash of the calldata and the decoded UTF-8
- **Validator run** — the validator's score, the delta, the consensus
  result
- **Logs** — the timestamped console log of the leader's API calls

## Buttons (state B, 5 in total)

- **View raw evidence** (primary, filled) — opens modal
- **Anchor release** (ghost) — the most common next action
- **View on Etherscan ↗** (link)
- **View on MusicBrainz ↗** (link)
- **File dispute** (warn) — the destructive action

## Trade-offs

- Strong at: the full narrative in one place. The user can see what
  registration feels like, what the result looks like, and what the
  deep-inspect view contains — all on one URL.
- Weak at: page weight (~36 KB of HTML, lots of inline styles).
  Real product would split this into routes, not a single file.

## Best for

- **The single deliverable for design review.** Show this to a
  reviewer and they can walk through the entire flow in 30 seconds.
- **The reference implementation.** If/when this gets built, this
  file is the spec — every component (split-pane, cert, modal, flow
  controller) is the source of truth.
- **A demo at the next GenLayer pitch.** Click through A → B → C,
  explain what the contract does, ship.
