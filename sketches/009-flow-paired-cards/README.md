# Variant 009 — Flow: paired (form + cert, both always visible)

## Design stance

A third stance: no transition, no expanding. The calm certificate and
the live form are **always visible** side by side. Compact form on the
left, full certificate on the right. Designed for power users who
don't want to lose their form state, and for the "I want to see what
just got verified while I keep editing" case.

## Key choices

- **Form on the left** (380px wide, scrollable): artist name, display
  name, wallet, IPI, two source fields. No submit button — the cert
  on the right updates as the user types.
- **Certificate on the right** (1fr, scrollable): the full 001 layout
  with all 13 cross-reference rows, the 94/100 score, the action
  button bar.
- **Live indicator** in the header: small green dot + "live" pill.
- **No transition, no second URL, no modal.** Just two scrollable
  panes that update together.

## Buttons (split 2 + 3)

Form (left):
- **Reset** (ghost) — restore defaults
- **Export JSON** (primary) — download the current claim as JSON

Certificate (right):
- **Anchor release** (ghost)
- **View raw evidence** (link) — could open the 005 modal
- **View on Etherscan ↗** (link)
- **File dispute** (link, warn color)

## Trade-offs

- Strong at: power users who iterate on the form, "show me while I
  type" use case, no mental context switch between states
- Weak at: small viewports (the form pane needs ~320px to be
  usable; below 800px this design falls apart), the user who arrives
  for the certificate and is overwhelmed by the form pane

## Best for

- Internal tools used by label/manager staff
- The "I'm a developer setting up my artist's claim" case
- A future "edit existing claim" view, where the user needs to see
  what they're changing while they change it
