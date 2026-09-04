# Variant 002 — Utilitarian dense

## Design stance

Treat verification output like an engineering console. JetBrains Mono, dark
theme, every signal on screen at once. Optimized for power users who
already understand the protocol and want to debug scoring.

## Key choices

- Layout: 3-pane (artists list · evidence detail · scoring + console)
- Typography: JetBrains Mono / SF Mono monospace
- Color: near-black `#0e0f12`, teal accent `#5eead4`, semantic badges
  (ok/warn/err)
- Interaction: tabbed top bar (register_artist / anchor_release /
  dispute / is_verified_human), scrolling log console at the bottom

## Trade-offs

- Strong at: density, technical detail visibility, batch operations
  across many artists, debugging
- Weak at: newcomer onboarding, "this is a beautiful artifact" feel

## Best for

- The contract deployer's own console (a developer or operator running
  the testnet)
- Auditors reviewing disputes
- Anyone debugging "why did this artist score 18 instead of 70"
