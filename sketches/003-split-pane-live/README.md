# Variant 003 — Split-pane live

## Design stance

Treat verification as a single continuous action: the user enters a claim
on the left, and the right pane shows the cross-reference results
updating in real time. Designed for the moment of registration itself,
not the aftermath.

## Key choices

- Layout: 50/50 split, two columns, no top nav
- Typography: Inter / system sans, generous 14px
- Color: paper background, blue accent `#2563eb`, green ok / red err
- Interaction: 13-platform source dropdown (Spotify, Bandcamp, IPI,
  etc.), live status pulse on the right ("resolving…resolved"),
  13-tile matrix showing hit/miss per source at a glance

## Trade-offs

- Strong at: registration moment UX, transparency of the cross-reference
  process, education ("here's exactly what we checked")
- Weak at: post-registration viewing, multi-artist browsing, dense
  technical info

## Best for

- The actual `register_artist()` call from an end-user web app
- Onboarding flows where the user is providing their own data
- Showing real-time what evidence is being collected as the user types
