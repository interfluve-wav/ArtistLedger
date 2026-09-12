# Loom — ArtistLedger demo (≤90 sec)

**Goal**: honest, working demo that lands the Onchain Justice track.
Speak slowly; 90 sec is tight. Don't read this on camera — memorize
the beats, paraphrase, use the numbers on the screen.

---

## Before you hit record

- 1280x800 Chrome, fullscreen, no bookmarks bar.
- Open `https://artistledger-frontend.vercel.app/`.
- Have `AGENT_TANK_SUBMISSION.md` open in another window as reference.

## Address sanity check (do this FIRST)

1. Confirm the header reads `0x703AdAB…4384 (v0.3.4)` and shows
   `connected · N methods`.
2. If not, **stop recording, redeploy Vercel, restart**. A demo
   with a stale address in the header loses the panel in 5 sec.

## The beats (90 sec, in this order)

| Beat | Time | What to do | What to say (one-liner) |
|---|---|---|---|
| 1. Hook | 0–10s | Look at camera | "Today anyone can claim to be Caribou. ArtistLedger is a GenLayer Intelligent Contract that adjudicates whether a music artist is real — by reading free public APIs and resolving the answer on-chain." |
| 2. Live demo | 10–20s | Point at the header | "Deployed to GenLayer studionet. Header shows `connected · N methods` — the contract is alive." (Don't read the address aloud — visual evidence is enough.) |
| 3. Submit | 20–45s | Click "Connect" → pick Caribou → click "Also include Bandcamp…" → submit. Wait ~30-60s for VRFD. | "I just submitted Caribou with real Apple Music + MusicBrainz IDs. The leader ran the public-API checks, validators re-derived the score, and the badge flipped to VRFD." |
| 4. Strict score | 45–60s | Point at the cert "31/100 strict · 73/100 lenient · VRFD" | "The strict on-chain score is [N]/100 — below the 70-point threshold for Verified. The contract is doing its job: refusing to rubber-stamp an artist without an audio fingerprint. We don't fake it." |
| 5. Inspect modal | 60–75s | Click "C · inspect" → Evidence JSON tab | "Every claim on-chain is auditable. The Evidence object is populated by the leader — apple_music_artist_id, soundcloud_handle, isrc_codes, the whole 27 fields." |
| 6. Close | 75–90s | Look at camera | "Open source on GitHub — interfluve-wav/ArtistLedger. Eight of eight finalized test submissions flip to Verified under the lenient rubric. Built for Agent Tank, Onchain Justice track." |

## If the strict score on the day isn't 31

**Don't fake it.** Paraphrase beat 4:

> "The strict on-chain score is below 70 — the contract refusing to
> rubber-stamp without an audio fingerprint is the WHOLE POINT.
> Here's the lenient projection the demo uses so the panel can see
> what Verified would look like under a friendlier rubric."

The strict number is read off the cert, not the script. The lenient
number is also read off the cert. Both are right there.

## If the lenient score on the day isn't ≥60 (no VRFD)

**Stop the demo.** The lenient rubric is calibrated to flip real
artists with at least one tier-1 + tier-2. If it isn't flipping,
something regressed — check:

1. Is the contract version still v0.3.4?
2. Is `require_two_source` (strict mode) unchecked?
3. Does `data.matchCount` show 2/2 in the modal?
4. Did you click "Also include Bandcamp…"?

If 1-3 are wrong, fix and restart. If 4 was missed, redo the submit.

## After recording

1. Upload to Loom, set to **public**.
2. Copy URL (`https://www.loom.com/share/<id>`).
3. Paste into the Demo Video field of the submission form.

## Common mistakes

- **Reading word-for-word on camera** — the panel can tell. Memorize
  the beats, paraphrase.
- **Going over 90s** — attention drops hard. Cut beats 5 and 6 first
  if running long, never cut beat 1 (the hook).
- **Apologizing for strict < 70** — it's the contract working. Lead
  with "the contract is doing its job".
- **Including the wallet seed** — "Connect" generates a
  throwaway key in localStorage. Don't paste anything from chat.
- **A bad Loom is worse than no Loom** — if rushed, skip and submit
  with the How-To text instead.
