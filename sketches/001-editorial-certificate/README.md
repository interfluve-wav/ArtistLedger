# Variant 001 — Editorial certificate

## Design stance

Treat verification output like a notarized document. Calm serif typography, centered
single column, generous whitespace. The "feel" is closer to a diploma or a
document of title than a SaaS dashboard.

## Key choices

- Layout: single column, max-width 760px, centered
- Typography: Iowan Old Style / Garamond serif (system fallback)
- Color: paper cream `#f7f3ec`, ink black `#1a1814`, rust accent `#8a3a1f`
- Interaction: two buttons at the bottom — primary "Anchor release", ghost
  "Download certificate (PDF)"

## Trade-offs

- Strong at: legibility, trust signaling, "this is real" feel
- Weak at: density, multiple-artist scanning, technical detail visibility

## Best for

- Showing a single verified artist as a shareable artifact
- Public-facing profile pages, embed widgets, certificate downloads
- Reviewers who need to read a single claim end-to-end without distraction
