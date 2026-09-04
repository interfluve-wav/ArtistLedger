# Variant 005 — Minimal modal

## Design stance

Same minimalism as 001, but with one big "View raw evidence" button that
opens a fullscreen modal containing 4 sub-tabs (Evidence JSON, Calldata,
Validator run, Logs). The certificate stays clean; the modal is the
"engine room."

## Key choices

- Layout: single column certificate (inherits 001), modal is 920px max
- Typography: same paper/serif/mono palette
- Color: paper cream + ink + rust accent
- Interaction: vanilla JS (no framework), `Esc` closes the modal, click
  outside the modal closes it
- The modal opens with `Evidence JSON` selected; switching tabs is
  one click; closing is `Esc` or click-outside or the close button

## Buttons (7 in total, but only 1 is primary)

- **View raw evidence** (primary, filled) — opens the modal
- **Anchor release** (ghost)
- **Download certificate** (ghost)
- **View leader → validator calldata** (link) — opens modal pre-set to Calldata tab
- **View on Etherscan ↗** (link)
- **View on MusicBrainz ↗** (link)
- **File dispute** (link)

## Modal tabs (4)

- **Evidence JSON** — the full leader.run_nondet_unsafe output as
  pretty-printed JSON with syntax highlighting
- **Calldata** — the hex-encoded calldata passed leader → validator
- **Validator run** — what the validator re-ran and the delta in score
- **Logs** — the timestamped console log of the leader's API calls

## Trade-offs

- Strong at: progressive disclosure (clean default, deep detail on demand),
  technical transparency without overwhelming the default view
- Weak at: keyboard-only navigation (no focus trap in the modal),
  screen-reader semantics (the modal isn't a true ARIA dialog)

## Best for

- The "explain the verification" use case — when someone asks "how do
  you know this is really Skee Mask?", you click once and show them
- A debug view for the deployer that doesn't need to live in a
  separate console
- A shareable artifact that can also be inspected in depth
