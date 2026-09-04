# Variant 008 — Flow: minimal → expand (calm by default)

## Design stance

The opposite of 007. Start on the minimal certificate (001) and grow
detail on demand. Two ways to go deeper: click an evidence row to see
the raw API response inline (the 004 pattern), or click "View raw
evidence" to open the modal with the full technical detail (the 005
pattern). The page never moves, only the depth of detail changes.

## Key choices

- **Default state:** the 001 minimal certificate, paper aesthetic,
  001/006 button pattern. Calm by default.
- **Inline expand:** every evidence row is a `<details>` element.
  Click → see the JSON payload. 10 expandable rows total.
- **Modal expand:** one button → 4-tab modal (Evidence JSON, Calldata,
  Validator run, Logs) for the "show me everything" case.
- **No state 2, no second URL.** Everything happens in place.

## Buttons (5 in the always-visible state)

- **View raw evidence** (primary, filled) — opens the modal
- **Anchor release** (ghost) — the most common next action
- **View on Etherscan ↗** (link)
- **View on MusicBrainz ↗** (link)
- **File dispute** (link, warn color)

## Trade-offs

- Strong at: progressive disclosure, the calm default, the "I don't
  need to see all this" default, the user who lands on this page from
  a shared link and only wants the score.
- Weak at: the 10 `<details>` rows make the page longer than 001
  even when collapsed (each row has its summary visible).

## Best for

- A public-facing certificate that's also useful to auditors
- The "I just want to verify this looks right" use case
- Embeds, shared links, public profile pages
