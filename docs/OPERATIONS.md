# ArtistLedger — Current-State Reference (2026-09-13)

> Reader: this is the canonical snapshot of how the system works RIGHT NOW,
> including live on-chain state, credentials wiring, and known bugs. Read
> this before touching anything. Companion docs: `ARCHITECTURE.md`
> (design rationale), `FIXLOG.md` (every fix + how verified), `PENDING.md`
> (work queued), `AGENT_TANK_SUBMISSION.md`.

## 1. What the app is

ArtistLedger = an on-chain artist-provenance registry on GenLayer (studionet).
An artist claims an identity; the contract's leader collects evidence from
public sources (music catalogs + the artist's own profiles); validators
re-derive and cross-check the evidence; consensus votes; score >= 70 =>
"VRFD" certificate anchored on-chain.

Frontend: dark operator-console UI (Vercel).
Contract: `contracts/ProvenanceRegistry.py` (Python, GenVM).
Test harness: `scripts/ownership_live_test.py` (off-chain live profile checks).

## 2. On-chain state (LIVE, 2026-09-13)

| Item | Value |
|---|---|
| NEW contract (current code, all features) | `0x214DBC690f02d2651B4564771fB1094D3A1FDB76` |
| Deploy tx | `0x6a80e7ea61348eaafec766b8ada22da924041b6ed6128dced3c82132f37b386f` |
| OLD contract (v0.3.4, pre-proofs — do NOT use) | `0x703AdAB82751A9006aFE9c477DC344f8D9CA4384` |
| Chain | studionet (chainId 61999), **gasless** (0 GEN is normal — docs confirm) |
| Deployer account | `provenance-deployer` = `0x08876a74135586bd04d758dc50a9b68a934aebc1` |
| Keystore pw | `/root/.genlayer/keystore-pass-provenance-deployer` (chmod 600) |
| Active CLI config | `genlayer config get` → network `studionet`, account `provenance-deployer` |

Deployed contract methods (12): `register_artist`, `set_api_keys`,
`set_lastfm_key_pool`, `set_spotify_key_pool`, `anchor_release`, `dispute`,
`get_artist`, `get_dispute`, `get_release`, `get_lastfm_pool_size`,
`get_spotify_pool_size`, `is_verified_human`.

## 3. Deploying / interacting (proven commands)

Studionet is GASLESS — no faucet, no funding. 0 GEN is expected.

```bash
# Deploy (password from keystore file, piped — never printed)
cat /root/.genlayer/keystore-pass-provenance-deployer | \
  genlayer deploy --contract contracts/ProvenanceRegistry.py

# Read view
cat /root/.genlayer/keystore-pass-provenance-deployer | \
  genlayer call 0x214DBC690f02d2651B4564771fB1094D3A1FDB76 get_spotify_pool_size

# Write (args: JSON array — see known bug #1)
cat /root/.genlayer/keystore-pass-provenance-deployer | \
  genlayer write <ADDR> set_lastfm_key_pool --args '["key1","key2"]'

# Schema check (deploy pre-flight; must print SCHEMA OK)
.venv/bin/python scripts/studio_schema_probe.py contracts/ProvenanceRegistry.py
```

## 4. Key wiring

All secrets live OUTSIDE the repo: `/root/projects/ArtistLedger/.env` (chmod 600)
and `/root/.secrets/` (chmod 600). **Never paste secrets into chat — a
key shown in chat is considered burned and must never be wired.**

| Env var | What | On-chain? |
|---|---|---|
| `ACOUSTID_API_KEY` | AcoustID fingerprint | via `set_api_keys` |
| `SPOTIFY_CLIENT_ID`/`_SECRET` (+ `_2`, `_3`) | 3 own-app Spotify pairs, client-credentials mint | via `set_spotify_key_pool` |
| `LASTFM_KEY_POOL` | 14 fresh Last.fm keys (comma-separated) | via `set_lastfm_key_pool` |

Repo guards: `scripts/check_no_keys.sh` runs on every push (pre-push hook) and
before every auto-deploy — any key material in the tree blocks hard.
`.gitignore` covers `*.keystore`, `*.pem`, `UTC--*.json`, `.secrets/`,
`wallet*.json`, `keys.enc`, etc.

## 5. Scoring model (current weights)

```
Tier 1 catalog (max 45):  AcoustID +20 | ISRC +10 | Spotify +10 (name-bound)
                          | Apple +5
Tier 2 (max 20):          Bandcamp +3 | SoundCloud +3 | Instagram +2 | Last.fm +2
Two-source agreement:     2 sources +15 | 1 source +8
OWNERSHIP PROOFS (Tier 2.6): +25 per confirmed channel, MAX 2 channels = +50
Wallet:                   age +5 | name/ENS +5
LLM:                      ±5 bounded
Existence baseline:       +5
VERIFY THRESHOLD: 70    DISPUTE THRESHOLD: 60
```

Key design facts:
- **Ownership proofs are the strongest signal** (token in artist's own
  profile bio/description proves control of the identity's public surface).
  W_OWNERSHIP_PROOF was raised 12 → 25 so two proofs alone nearly verify.
- **Absence of catalog presence (not on Spotify etc.) does NOT lower score**
  — catalogue tiers are bonus margin, not gates.
- Last.fm proof requires ≥200 lifetime scrobbles (sybil floor).
- Two proofs + two-source agreement + baseline = 75 → verified with no catalog.
- LLM adjustment bounded ±5; score clamped [0,100].

## 6. Ownership-proof tokens (ALVERIFY)

Format: `ALVERIFY-<16 base32 chars>-<unix hour>` (hour granularity keeps it
stable within a session, unique per claim).

**User decision (2026-09-13): token should be STABLE per person**, not
regenerated hourly. Desired scheme: derive from wallet address so one person
reuses the same token; validated artists may remove the token from bios —
the on-chain evidence is captured at verification time and persists.

CURRENT LIVE TOKEN (Interfluve): `ALVERIFY-KR4E3XCW4JB6N44N-497018` —
placed in YouTube description, SoundCloud bio, Last.fm profile. All three
verified PASS via harness (see §7).

## 7. Live verification results (harness, real profiles)

```bash
.venv/bin/python scripts/ownership_live_test.py \
  --token ALVERIFY-KR4E3XCW4JB6N44N-497018 \
  --youtube interfluve --lastfm interfluve --soundcloud interfluve \
  --artist "Interfluve"
```
→ SoundCloud PASS (bio 802 chars) · YouTube PASS (desc 253 chars) ·
Last.fm PASS (3,580 scrobbles ≥ 200) · Spotify "no result" (artist genuinely
NOT on Spotify — absence is 0 bonus, not negative).

Interfluve wallet: `0xE78940B6EE98b00B1017F1302b1896fb9E3C79c1`
Realistic score on-chain once keys wired: **75/100 = VRFD** (50 proofs + 15
two-source + 5 maturity + 5 baseline).

## 8. Known bugs / open items

1. **`set_lastfm_key_pool`/`set_spotify_key_pool` writes ACCEPTED but reads
   return 0** (2026-09-13). Both pools seeded via `genlayer write`; writes
   report ACCEPTED / "Write operation successfully executed", but
   `get_lastfm_pool_size` and `get_spotify_pool_size` return 0. Even a
   minimal `["abc..."]` pool reads 0. Root cause not yet found — suspect:
   (a) GenVM list-param ABI mismatch with `genlayer write --args` array
   syntax; (b) storage readback issue with the JSON-string fields. The
   DEFAULT param + JSON-string storage is correct per schema probe. This
   needs the same negotiation the successful `set_spotify_key_pool` (3 pairs,
   reads 3) had — note: Spotify pool READ 3 correctly, Last.fm reads 0!
   **So the mechanism works**; the Last.fm args shape is the suspect.

2. **Frontend still points at OLD contract.** `frontend/app.js:13`
   `CONTRACT = "0x703AdAB..."` + UI chips show v0.3.4. Must update to
   `0x214DBC690f02d2651B4564771fB1094D3A1FDB76` + version label before the
   live cert can show real scores. This is a plain string swap, smoke-test
   against the new address.

3. **`set_api_keys` (AcoustID/Spotify single/lastfm single) not run on new
   contract** — pools are seeded (spotify=3 confirmed) but the legacy single
   keys via `set_api_keys` haven't been called; contract still needs it if
   the pool fallback path is insufficient.

4. **Stable per-wallet token scheme** — not yet implemented (see §6): the
   token is currently client-side generated with an hour suffix. Needs
   wallet-address-derived token so it survives reloads and matches the user's
   "one token forever" requirement.

5. **Auto-deploy watcher**: cron `*/5 * * * *` runs `scripts/autodeploy.sh`,
   hard-resets to origin/main, deploys frontend to Vercel. Log:
   `/var/log/artistledger-autodeploy.log`. Note: watcher deploys the FRONTEND
   only; contract deployments are manual via genlayer CLI (§3).

## 9. Repo map (current)

| Path | Role |
|---|---|
| `contracts/ProvenanceRegistry.py` | The contract (1857 lines) |
| `frontend/index.html` + `app.js` | Dark console UI; **51 DOM hooks preserved across reskin; app.js talks to page ONLY via IDs** |
| `scripts/ownership_live_test.py` | Off-chain live harness (real HTTP via gl stub) |
| `scripts/studio_schema_probe.py` | GenVM schema pre-flight |
| `scripts/check_no_keys.sh` (+ install_hooks.sh) | Secret guard |
| `scripts/autodeploy.sh` | Vercel watcher |
| `docs/ARCHITECTURE.md` / `FIXLOG.md` / `PENDING.md` | Design, fixes, queue |
| `tests/` (130 passing) | Contract + harness tests |

## 10. Guard rails (non-negotiable)

- No secrets in chat; keys in `.env` / `/root/.secrets/` only; chmod 600.
- No pushes to `interfluve-wav` without per-push go-ahead.
- No automated account creation, no API-key hunting/scraping, no jailbreak
  personas — regardless of framing.
- Token-managed profiles: token inserted by the artist themselves into their
  OWN bios. We test/read; we never fabricate a match.