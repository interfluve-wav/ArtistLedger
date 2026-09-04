# Variant 004 — Minimal expandable

## Design stance

Same minimalism as 001, but every evidence row is a `<details>` element —
click to expand the row and see the full raw API response. Calm paper
style preserved. No modal, no overlay — all the detail lives inline in
the document.

## Key choices

- Layout: single column, max-width 740px, centered (inherits 001)
- Typography: Iowan Old Style serif body, SF Mono for evidence IDs and JSON
- Color: paper cream + ink + rust accent, no change from 001
- Interaction: native `<details>`/`<summary>` HTML elements, no JS
- 8 evidence rows: 2 from two-source, 6 from public-data cross-reference
- All rows show a directional caret (▸ / ▾), and the source label changes
  to rust accent when expanded

## Buttons (5 in total, all at the bottom)

- **Anchor release** (primary, filled) — the most common next action
- **Download certificate** (ghost) — share the artifact
- **View on Etherscan ↗** (link) — outbound to chain explorer
- **View on MusicBrainz ↗** (link) — outbound to source DB
- **File dispute** (link) — contest the verification

## Trade-offs

- Strong at: information density without visual clutter, technical
  transparency, all signals visible to anyone curious enough to click
- Weak at: very long evidence payloads (the JSON box gets long), mobile
  (the grid layout collapses awkwardly below 600px)

## Best for

- The engineer's view of the same certificate as 001
- Auditors who need to see the raw API responses, not just the score
- A "details" view that complements the simpler 001 default
