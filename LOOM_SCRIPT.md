# Loom script — ArtistLedger demo (≤90 seconds)

**Goal**: show the panel an honest, working ArtistLedger demo. Pace yourself
— 90 seconds is tight. Speak slowly, don't rush. The portal says
"video pitches and shortlisted ideas earn more", so a polished Loom
moves you up the ranking.

## Setup before recording (30 sec)

1. Open https://artistledger-frontend.vercel.app/ in a clean Chrome
   window at 1280x800 (or larger). Make sure your face-cam or no-cam
   shows the site taking up most of the screen.
2. Hide bookmarks bar, close other tabs.
3. Open the [AGENT_TANK_SUBMISSION.md](AGENT_TANK_SUBMISSION.md) once
   in another window as a reference — don't read from it on camera.

## Script (read this verbatim, ~85 sec total)

> **[0-10 sec — open with the hook]**
>
> "Today anyone can claim to be Caribou. ArtistLedger is a GenLayer
> Intelligent Contract that adjudicates whether a music artist is
> real, by reading 8 free public APIs and resolving the answer
> on-chain."
>
> **[10-20 sec — point at the live demo header]**
>
> "Here's the live demo — deployed to GenLayer studionet at
> `0x703AdAB…4384`. Header shows 'connected · 8 methods' once
> Studio RPC is reachable."
>
> **[20-40 sec — run a Caribou submit]**
>
> [click "Use local account" → wallet appears]
> [open "Try an artist" → pick Caribou]
> [click "Also include Bandcamp/SoundCloud/Instagram/Last.fm" → 6 rows]
> [click "Sign & submit proof →"]
> [wait for VRFD badge, ~30-60 sec]
>
> "I just submitted Caribou with real Apple Music + MusicBrainz IDs.
> The leader ran 8 API checks, validators re-derived the score, and
> the badge flipped to VRFD. The strict on-chain score is 31 — below
> the 70-point threshold for Verified — but the contract is doing
> exactly what it should: refusing to rubber-stamp an artist without
> an audio fingerprint."
>
> **[40-55 sec — show the lenient rubric + breakdown]**
>
> [point at the cert showing "31/100 strict · 73/100 lenient · VRFD"]
>
> "We don't fake the score. The contract returns 31, and we show both
> the strict number and a friendlier projection side-by-side so
> anyone can see exactly what the on-chain truth is versus what a
> real artist looks like in practice."
>
> **[55-75 sec — show the Inspect modal]**
>
> [click "C · inspect"]
> [click "Evidence JSON" tab]
>
> "Here's the typed Evidence object the leader returned — populated with
> apple_music_artist_id, soundcloud_handle, isrc_codes, the whole 27
> fields. Every claim on-chain is auditable."
>
> **[75-90 sec — close]**
>
> "Open source on GitHub — github.com/interfluve-wav/ArtistLedger.
> Eight of eight finalized test submissions flip to Verified under the
> lenient rubric. Built for the Agent Tank Hackathon, Onchain Justice
> track."
>
> [end recording]

## Post-recording

1. Upload to Loom, set to **public** (panel needs to view without
   login).
2. Copy the Loom URL (looks like `https://www.loom.com/share/<id>`).
3. Paste it into the **Demo Video** field of the submission form.
4. Submit the form.

## Common mistakes to avoid

- **Don't** read the script word-for-word on camera. Memorize the
  beats (hook → live demo → submit → VRFD → inspect → close) and
  paraphrase. The panel can tell when you're reading.
- **Don't** go over 90 seconds — Loom cuts off at the free tier's
  5-minute mark anyway, but the panel attention span drops hard
  after 90s.
- **Don't** include your private key or wallet seed in the recording.
  Just click "Use local account" — the SDK generates a throwaway key.
- **Don't** apologize for the strict score being below 70. That's
  the contract doing its job. Lead with the lenient rubric story.

## If you can't record a Loom

The Demo Video field is optional. You can submit without it.
The How-To field already walks the panel through the demo verbally,
and they can do it themselves in <2 min. A bad Loom is worse than no
Loom — skip it if you're rushed.
