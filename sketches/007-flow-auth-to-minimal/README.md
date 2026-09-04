# Variant 007 — Flow: live → minimal (after auth)

## Design stance

Start where 003 (split-pane, live) ends. The user is filling out a claim
on the left; live cross-reference is running on the right. When they
click "Sign & submit proof", the split-pane fades and the screen
**settles** into the 001 minimal certificate. One screen, one
transition, no second route.

## Key choices

- **State 1 (default):** full 003 layout — form on left, live verification
  on right. The right pane shows the matrix, source cards, score banner,
  per-source check details.
- **State 2 (post-auth):** the 001 minimal certificate appears, the
  split-pane fades out. Header and network context stay the same.
- **Transition:** 0.6s opacity fade on the split, then 0.8s fade-in on
  the cert. No second URL, no modal.
- **Demo bar** at the bottom right toggles between states (since this
  is a static sketch and you can't actually sign anything).

## Buttons (5 in the post-auth state)

- **Anchor release** (ghost, primary action)
- **View raw evidence** (link) — same modal as 005
- **View on Etherscan ↗** (link)
- **View on MusicBrainz ↗** (link)
- **File dispute** (link, warn color)

## Trade-offs

- Strong at: a single, clear narrative (do this → see this). The
  transition rewards the action.
- Weak at: server-state mismatches (if the verification actually takes
  30s, the form sits there idle). Also: the demo bar is a sketch-only
  affordance, the real product would auto-advance.

## Best for

- The full registration moment, start to finish, in one view
- Showing reviewers "this is what the user does, then sees"
- Demos where the flow matters as much as the destination
