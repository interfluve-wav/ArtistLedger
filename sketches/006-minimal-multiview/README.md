# Variant 006 — Minimal multi-view

## Design stance

Same minimalism as 001, but a 4-tab strip at the top lets the user
switch between the 4 contract actions: register_artist, anchor_release,
dispute, is_verified_human. Each tab is its own minimal certificate;
the chrome (font, palette, layout, button pattern) stays constant.

## Key choices

- Layout: 4-tab strip at top, single column below (inherits 001)
- Typography: same paper/serif/mono palette
- Color: same paper cream + ink + rust accent, with `.warn` and `.err`
  variants for the dispute view
- Interaction: vanilla JS tab switching (no framework), no animation,
  just an underline indicator on the active tab
- Buttons use vertical separator lines between groups (primary, ghost,
  outbound, destructive)

## The 4 views

### register_artist (the original 001)

Same as the first sketch. 2 sources matched, 5/13 cross-references
hit, score 94/100. Primary action: View raw evidence. Outbound:
Etherscan + MusicBrainz. Destructive: File dispute.

### anchor_release

A release certificate. Same chrome, different content. "Compro" by
Skee Mask, Ilian Tape, 2018-06-15. Audio hash is the anchor. Cross-
references to MBID, Discogs, Spotify, Apple Music — all matched.
Score 98/100. Outbound: every platform the release lives on.

### dispute

A dispute is contested. Disputant wallet, target artist, evidence,
score. Most disputes score low because the disputant doesn't have
sources. This view shows a DISMISSED dispute at 12/100 (threshold
60 to uphold). Different color: `seal.warn` instead of `seal.VRFD`.

### is_verified_human

The query view, shortest. The "True" verdict is the centerpiece. Shows
the return shape, gas cost (~24k), and the typical use cases (x402
payment gate, gated mint, sybil resistance). The actionable button
is "Embed this attestation."

## Trade-offs

- Strong at: one consistent design system across all 4 contract actions;
  users learn the pattern once, apply it everywhere
- Weak at: tab strips on mobile (the subtitles wrap awkwardly below
  600px); some users don't notice the tabs and assume the page is only
  the register_artist view

## Best for

- A whole-app design where every screen looks like the others
- The "this is one product" feel — the user doesn't have to context
  switch between different chrome
- Showing reviewers how a single design language extends across
  every action
