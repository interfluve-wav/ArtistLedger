# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# ruff: noqa: BLE001,S110
"""
OnChainProvenanceRegistry — GenLayer Intelligent Contract v0.7.2

Tracks real-world music releases with provenance validated through
deterministic cross-source verification + LLM qualitative adjustment.
Answers one question: is this audio track provably human-made and unaltered?

v0.7.0 — identity rotation (reverify). The verified identity is the
PROFILE CLUSTER, not the wallet: `reverify()` re-points a verified
identity to a new wallet when the artist proves control of the same
profiles again (fresh ALVERIFY token), revoking the old wallet. One
identity = one current wallet; keys are revocable pointers.

v0.7.1 — hardening (independent review): per-platform same-profile rule
(a handle squatted on a platform the artist never used can't claim the
identity); revocation is DERIVED from the record (a recovered/fresh
identity on a marked wallet reads verified — marker only shades dead
records); revoked wallets lose anchor_release power (no hash squatting);
validators recompute every deterministic reverify field instead of
trusting the leader.

v0.7.2 — validator floor accepts ownership proofs. An artist with zero
catalog presence (no Apple/Spotify/AcoustID) but a CONFIRMED ALVERIFY
proof on their own profile is real — the token is stronger evidence than
a scraped catalog ID. The anti-phantom floor now accepts any verified
ownership proof (before: every such artist hit MAJORITY_DISAGREE no
matter how real, e.g. Interfluve).

Architecture:
  Phase 1 — Leader collects 13 structured evidence fields by hitting
            8+ free public APIs (AcoustID, MusicBrainz, Spotify, Apple
            Music, Bandcamp, SoundCloud, Instagram, Last.fm, ENS,
            Etherscan, Farcaster).
  Phase 2 — Leader computes a deterministic 0-100 score from a weighted
            sum of the structured factors.
  Phase 3 — LLM makes a small ±5 qualitative adjustment based on whether
            the sources tell a consistent biographical narrative.
  Phase 4 — Validators re-fetch all sources independently, re-derive
            the evidence, and accept if both the evidence structs match
            and the final score is within a 15-point tolerance band.

The 70-point verification threshold has a real meaning now: an artist
needs AcoustID match + Spotify presence + MusicBrainz + at least 2
tier-2 sources, OR equivalent coverage, to pass. Fabricated identities
with no cross-source corroboration cannot reach 70.

The asymmetric dispute threshold (60 vs 70) means a single piece of
strong contrary evidence (e.g., a sample-match showing the audio is
Suno-generated) can flip a release to contested.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from genlayer import *

# ─── Storage layouts ───────────────────────────────────────────────────────
# GenVM allows exactly ONE gl.Contract subclass per contract file (the
# registry itself). Entity records are plain @allow_storage dataclasses,
# which TreeMap stores natively (same pattern as Evidence below).

@allow_storage
@dataclass
class Artist:
    wallet: Address
    did: str
    name: str
    verified_at: u256
    score: u256
    evidence: str  # JSON-serialized Evidence for onchain auditability
    require_two_source: bool  # strict mode: registration needs 2 matching sources


@allow_storage
@dataclass
class Release:
    artist: Address
    title: str
    audio_hash: bytes
    contributors: DynArray[Address]
    release_date: u256
    anchored_at: u256
    contested: bool


@allow_storage
@dataclass
class Dispute:
    audio_hash: bytes
    claimant: Address
    claim: str
    evidence_url: str
    filed_at: u256
    resolution: str


# ─── Evidence dataclass (passed in leader/validator JSON) ─────────────────

@allow_storage
@dataclass
class Evidence:
    # Tier 1 — high signal, deterministic (max 45 points)
    acoustid_matched: bool
    acoustid_recording_mbid: str
    isrc_codes: DynArray[str]            # any present = full 10 pts
    spotify_artist_id: str
    spotify_verified: bool
    spotify_name_matched: bool           # top search hit binds to claimed name
    spotify_followers: u256
    spotify_popularity: u256             # 0-100
    apple_music_artist_id: str
    apple_music_track_present: bool

    # Tier 2 — medium signal from provided URLs (max 20 points)
    bandcamp_handle: str
    bandcamp_real_name: str
    bandcamp_location: str
    soundcloud_handle: str
    soundcloud_followers: u256
    soundcloud_verified: bool
    instagram_handle: str
    lastfm_scrobble_count: u256

    # Tier 2.6 — ownership proofs (artist-controlled token on their own
    # profile, max 24 points: W_OWNERSHIP_PROOF x2 channels)
    ownership_proof_soundcloud: bool     # ALVERIFY token in SoundCloud bio
    ownership_proof_lastfm: bool         # token in Last.fm journal/bio + ≥200 scrobble account
    ownership_proof_bandcamp: bool       # token in Bandcamp about/disco
    ownership_proof_youtube: bool        # token in YouTube channel description
    ownership_lastfm_scrobbles: u256     # account maturity (lifetime scrobbles)

    # Tier 2.5 — two-source verification (DISCO parity, claim + cross-ref)
    verification_source_1: str          # e.g. "spotify_url" / "bandcamp_url"
    verification_handle_1: str
    verification_source_2: str
    verification_handle_2: str
    verification_match_count: u256       # 0 / 1 / 2

    # Tier 5 — wallet-derived (max 10 points)
    wallet_age_days: u256
    ens_name: str
    ens_matches_artist: bool
    farcaster_fname: str

    # Tier 3 — qualitative (LLM judge, ±5 points)
    press_narrative_score: int          # -5 to +5

    # Tier 3b — LLM identity guard (SAME_ENTITY across sources?)
    llm_identity_match: bool            # True = sources describe the claimed artist

    def to_dict(self) -> dict:
        """Serialize this Evidence to a plain dict with JSON-safe values.

        GenVM's `run_nondet_unsafe` passes the leader's return value to
        validators as `gl.vm.Return.calldata`. If the wire format is a
        JSON string, `to_json(self.__dict__)` would throw on `DynArray`
        and `u256` values because they are not JSON-native. This method
        explicitly converts them so the JSON form round-trips cleanly.
        """
        from dataclasses import asdict, is_dataclass
        d = asdict(self) if is_dataclass(self) else dict(self.__dict__)
        # u256 and DynArray are not JSON-native; convert to primitives.
        for k, v in list(d.items()):
            # DynArray exposes .items() and iteration over a JSON list.
            if hasattr(v, "items") and callable(v.items) and not isinstance(v, (str, bytes, dict)):
                try:
                    d[k] = list(v)
                except TypeError:
                    d[k] = v
            # u256 is a numeric subclass; cast to int.
            elif hasattr(v, "__int__") and not isinstance(v, (bool, int, float, str, bytes)):
                try:
                    d[k] = int(v)
                except (TypeError, ValueError):
                    d[k] = v
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @staticmethod
    def empty() -> "Evidence":
        # NOTE: must NOT use DynArray[str]() here — GenVM's DynArray can
        # never be instantiated by user code (it raises TypeError). Plain
        # lists are used for in-transit evidence; storage snapshots convert
        # to lists in to_dict().
        return Evidence(
            acoustid_matched=False,
            acoustid_recording_mbid="",
            isrc_codes=[],
            spotify_artist_id="",
            spotify_verified=False,
            spotify_name_matched=False,
            spotify_followers=u256(0),
            spotify_popularity=u256(0),
            apple_music_artist_id="",
            apple_music_track_present=False,
            bandcamp_handle="",
            bandcamp_real_name="",
            bandcamp_location="",
            soundcloud_handle="",
            soundcloud_followers=u256(0),
            soundcloud_verified=False,
            instagram_handle="",
            lastfm_scrobble_count=u256(0),
            ownership_proof_soundcloud=False,
            ownership_proof_lastfm=False,
            ownership_proof_bandcamp=False,
            ownership_proof_youtube=False,
            ownership_lastfm_scrobbles=u256(0),
            verification_source_1="",
            verification_handle_1="",
            verification_source_2="",
            verification_handle_2="",
            verification_match_count=u256(0),
            wallet_age_days=u256(0),
            ens_name="",
            ens_matches_artist=False,
            farcaster_fname="",
            press_narrative_score=0,
            llm_identity_match=True,
        )


# ─── Constants ─────────────────────────────────────────────────────────────

VERIFICATION_THRESHOLD: u256 = u256(70)
DISPUTE_UPHOLD_THRESHOLD: u256 = u256(60)
VALIDATOR_TOLERANCE: u256 = u256(15)
REPUTATION_PENALTY_PER_UPHELD_DISPUTE: u256 = u256(10)

# Factor weights (sum to 100 max deterministic + ±5 LLM; ownership proofs
# can only substitute for weak tiers, the final max(0, min(100, …)) cap
# keeps the scale honest)
W_ACOUSTID: int = 20
W_ISRC: int = 10
W_SPOTIFY: int = 10
W_APPLE_MUSIC: int = 5
W_BANDCAMP: int = 3        # v0.3.4: rebalanced down to free 7 pts for two-source
W_SOUNDCLOUD: int = 3
W_INSTAGRAM: int = 2
W_LASTFM: int = 2
W_TWO_SOURCE_MATCH: int = 15
W_SINGLE_SOURCE_MATCH: int = 8
W_WALLET_AGE: int = 5
W_WALLET_NAME: int = 5
W_LLM_ADJUSTMENT_RANGE: int = 5
# Ownership proofs (Tier 2.6): artist-controlled token on their own
# profile. This is the STRONGEST identity signal in the contract — it
# proves control of the public profiles of the claimed identity, which
# no audio fingerprint or catalog binding can. Valued accordingly:
# W_OWNERSHIP_PROOF per confirmed channel, capped at TWO channels
# (W_OWNERSHIP_CAP) so one dedicated scammer with N accounts can't
# out-score a real artist — but two real proofs alone clear the 70
# threshold (50 + baseline 5 + tier-2 corroboration).
W_OWNERSHIP_PROOF: int = 25
W_OWNERSHIP_CAP: int = 2

# ─── Collector feature flags (2026-09-15) ────────────────────────────────
# Spotify + AcoustID disabled: studionet validator nodes have unreliable
# egress to accounts.spotify.com/api.spotify.com (and a real chromaprint
# pipeline is pending), so both signals stall evidence collection or score
# honestly low. Flip to True and redeploy to re-enable.
ENABLE_SPOTIFY: bool = False
ENABLE_ACOUSTID: bool = False
# Last.fm ownership-proof maturity floor: an account below this lifetime
# scrobble count is "fresh" — its token doesn't count as ownership proof.
LASTFM_SCROBBLE_FLOOR: int = 200

# API base URLs
ACOUSTID_URL: str = "https://api.acoustid.org/v2/lookup"
MUSICBRAINZ_ARTIST_URL: str = "https://musicbrainz.org/ws/2/artist/"
MUSICBRAINZ_RECORDING_URL: str = "https://musicbrainz.org/ws/2/recording/"
SPOTIFY_SEARCH_URL: str = "https://api.spotify.com/v1/search"
APPLE_MUSIC_SEARCH_URL: str = "https://itunes.apple.com/search"
ENSDATA_URL: str = "https://api.ensdata.net/"
ETHERSCAN_TX_URL: str = "https://api.etherscan.io/api"
FARCASTER_USER_URL: str = "https://api.farcaster.xyz/v2/user-by-cast-address"


# ─── HTTP helper ───────────────────────────────────────────────────────────

def _http_get(url: str) -> str:
    """GET a URL via the GenLayer non-deterministic web block."""
    resp = gl.nondet.web.get(url)
    return resp.body.decode("utf-8", errors="replace")


def _http_get_json(url: str) -> dict:
    """GET a URL and parse as JSON, returning {} on any failure."""
    try:
        body = _http_get(url)
        return json.loads(body)
    except Exception:
        return {}


# ─── Tier 1 factor collectors ─────────────────────────────────────────────

def _acoustid_lookup(audio_hash: bytes, acoustid_key: str) -> tuple[bool, str]:
    """Look up the audio hash in AcoustID. Returns (matched, recording_mbid)."""
    if isinstance(audio_hash, str):
        fp = audio_hash[2:] if audio_hash.startswith("0x") else audio_hash
    else:
        fp = audio_hash.hex()
    url = (
        f"{ACOUSTID_URL}?client={acoustid_key}"
        f"&duration=0&fingerprint={fp}&meta=recordings+releaseids"
    )
    data = _http_get_json(url)
    try:
        results = data.get("results", [])
        if results and results[0].get("recordings"):
            rec = results[0]["recordings"][0]
            return True, rec.get("id", "")
    except Exception:
        pass
    return False, ""


def _musicbrainz_isrc(recording_id: str) -> DynArray[str]:
    """Fetch ISRC codes for a MusicBrainz recording."""
    if not recording_id:
        return []
    url = f"{MUSICBRAINZ_RECORDING_URL}{recording_id}?inc=isrcs&fmt=json"
    data = _http_get_json(url)
    # plain list — DynArray can't be user-instantiated
    return [code for code in data.get("isrcs", [])]


def _musicbrainz_artist(name: str) -> dict:
    """Look up an artist on MusicBrainz. Returns top match or {}."""
    url = f"{MUSICBRAINZ_ARTIST_URL}?query={name}&fmt=json&limit=1"
    data = _http_get_json(url)
    artists = data.get("artists", [])
    return artists[0] if artists else {}


def _spotify_mint_token(client_id: str, client_secret: str) -> str:
    """Client-credentials OAuth: no user consent, returns a bearer token.

    Used when no long-lived token is stored. Note: since Feb-2026 the
    Spotify API omits `followers`/`popularity` for dev-mode apps, so the
    token's only job is artist search + name binding.
    """
    import base64
    import json as _json
    import urllib.request

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = _json.loads(resp.read().decode())
            return body.get("access_token", "")
    except Exception:
        return ""


def _spotify_search(name: str, spotify_token: str) -> dict:
    """Search Spotify for an artist. Returns top match or {}.

    NOTE (Feb-2026 API change): `followers` and `popularity` were removed
    from artist responses for dev-mode apps. Product code must not rely on
    them; the caller binds via `name` overlap instead. Extended-quota keys
    still receive the fields, so keep parsing them when present.
    """
    headers = {"Authorization": f"Bearer {spotify_token}"}
    url = f"{SPOTIFY_SEARCH_URL}?q=artist:{name}&type=artist&limit=1"
    try:
        resp = gl.nondet.web.get(url, headers=headers)
        data = json.loads(resp.body.decode("utf-8", errors="replace"))
        items = data.get("artists", {}).get("items", [])
        if not items:
            return {}
        top = items[0]
        top["_name_matched"] = _name_token_overlap(top.get("name", ""), name) >= 0.5
        return top
    except Exception:
        return {}


def _apple_music_search(name: str, title: str = "") -> tuple[str, bool]:
    """Search Apple Music. Returns (artist_id, track_present).

    `title` is a reserved hint: when a real release title is supplied it can
    scope the search to an exact track (Layer 2 refinement). For now the
    track search is name-scoped with a co-artist guard, matching the on-chain
    behaviour that verifies the artist's audio is present on Apple Music.

    Co-artist guard (v0.3.5 fix): the previous version accepted ANY track
    whose `artistName` contained the claimed name as a substring, then took
    the last match. For "Four Tet" this matched "Skrillex, Starrah & Four
    Tet" first and returned Skrillex's artistId — wrong artist.

    v0.3.5 fixes this by:
      1. Splitting `artistName` on `,` / `&` / `feat.` / `featuring` and
         checking each token segment for exact (case-insensitive) equality
         against the claimed name, not substring containment.
      2. Preferring exact matches over substring matches when both exist.
      3. Pinning `track_present` to True only when we find an exact-name
         track by the canonical artist.
    """
    url = f"{APPLE_MUSIC_SEARCH_URL}?term={name}&entity=musicTrack&limit=10"
    data = _http_get_json(url)
    results = data.get("results", [])
    name_lc = name.strip().lower()
    # Split artistName on common separators and check each segment.
    def _exact_segment(an: str) -> bool:
        if not an:
            return False
        an_lc = an.lower()
        for sep in [",", "&", " feat.", " feat ", " featuring ", " with ", " x "]:
            an_lc = an_lc.replace(sep, "|")
        for seg in an_lc.split("|"):
            if seg.strip() == name_lc:
                return True
        return False
    exact_id = ""
    exact_track = False
    substring_id = ""
    substring_track = False
    for r in results:
        if r.get("wrapperType") != "track":
            continue
        an = r.get("artistName", "")
        if _exact_segment(an):
            # Prefer the first exact match (it'll be the canonical artist)
            if not exact_id:
                exact_id = str(r.get("artistId", ""))
                exact_track = True
        elif name_lc in an.lower():
            if not substring_id:
                substring_id = str(r.get("artistId", ""))
                substring_track = True
    if exact_id:
        return exact_id, exact_track
    if substring_id:
        # Fall back to substring match but DON'T set track_present — the
        # canonical-artist guarantee isn't met. This means a co-artist-only
        # track won't bump the strict score.
        return substring_id, False
    return "", False


# ─── Tier 2 factor collectors (URL-based) ─────────────────────────────────

def _bandcamp_check(handle: str) -> tuple[str, str, str]:
    """Fetch a Bandcamp profile. Returns (handle, real_name, location).

    v0.3.6 fix: the previous version only looked for JSON-LD `"name":"..."`
    fields. Many Bandcamp artist pages (including verified artists like
    Mindex, boards-of-canada, burial) expose the artist name only via
    `<title>` and `<meta property="og:title">`. We now fall back through
    those plus a few other common locations.

    Also: handle may arrive as a full URL ("https://mindex.bandcamp.com/")
    or a bare handle ("mindex"). We normalize before building the
    fetch URL.

    Real name and location are still loose regex matches; if neither
    JSON-LD nor meta tags yield anything, both fields are empty and the
    downstream `_name_token_overlap` check will correctly fail.
    """
    if not handle:
        return "", "", ""
    # Normalize: extract bare handle from URL if needed
    h = handle
    if ".bandcamp.com" in h:
        # Full URL: extract the part before .bandcamp.com
        # e.g. "https://mindex.bandcamp.com/" → "mindex"
        h = h.split("://")[-1].split(".bandcamp.com")[0].rstrip("/")
    elif "/" in h:
        # Bare path: take the first segment
        h = h.split("/")[0]
    if not h:
        return "", "", ""
    url = f"https://{h}.bandcamp.com"
    try:
        body = _http_get(url)
        # Try JSON-LD name first (most structured); fall back to
        # og:title / twitter:title / plain <title>.
        real_name = _regex_any(body, (
            r'"name":"([^"]+)"',                                       # JSON-LD name
            r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',  # OpenGraph title
            r'<meta[^>]+name="twitter:title"[^>]+content="([^"]+)"', # Twitter title
            r'<title>([^<]+)</title>',                                 # plain <title>
        ))
        # Strip "| Mindex" / "Music | Mindex" → just "Mindex"
        if real_name and " | " in real_name:
            real_name = real_name.split(" | ")[0].strip()
        location = _regex_any(body, (
            r'"location":"([^"]+)"',
            r'<meta[^>]+property="og:locality"[^>]+content="([^"]+)"',
        ))
        return h, real_name, location
    except Exception:
        return h, "", ""


def _soundcloud_check(handle: str) -> tuple[str, int, bool]:
    """Fetch a SoundCloud profile. Returns (handle, followers, verified).

    v0.3.6 fix: GenVM's HTTP client sometimes returns a slightly
    different body than a regular browser/Python fetch (Cloudflare
    interstitial variants). The regexes are now more permissive — they
    tolerate optional whitespace, allow the value to be a JSON-escaped
    string, and fall back through several patterns.

    If the body has neither followers_count nor verified patterns,
    the leader falls back to a presence-only signal: a page that
    contains the artist's name in any form returns followers=0,
    verified=False — the caller will still count the page as a tier-2
    signal, just without the followers/verified bonus.

    v0.6.1 fix: the exception path returned `handle` (truthy) even when
    the fetch failed, so callers checking existence got a false positive
    for ANY input. Now returns ("", 0, False) on failure — callers must
    treat a failed fetch as "no page".
    """
    if not handle:
        return "", 0, False
    url = f"https://soundcloud.com/{handle}"
    try:
        body = _http_get(url)
        # followers — try several patterns
        followers_str = _regex_any(body, (
            r'"followers_count"\s*:\s*(\d+)',
            r'"followers"\s*:\s*(\d+)',
            r'"follower_count"\s*:\s*(\d+)',
            r'data-followers="(\d+)"',
        ))
        try:
            followers = int(followers_str) if followers_str else 0
        except ValueError:
            followers = 0
        # verified badge — try several
        body_lc = body.lower()
        verified = (
            '"verified":true' in body_lc
            or '"verified": true' in body_lc
            or '"pro":true' in body_lc
            or '"pro": true' in body_lc
            or '"verified_user":true' in body_lc
            or '"badges":' in body_lc
        )
        return handle, followers, verified
    except Exception:
        # v0.6.1: falsy on failure — a truthy handle here made
        # _verify_claimed_source pass for nonexistent pages
        return "", 0, False


def _soundcloud_display_name(handle: str) -> str:
    """Fetch a SoundCloud profile's display name (profile `username` in
    the embedded user JSON). Used to name-bind claimed SC sources —
    existence-only matching let attacker-owned pages pass (audit F1)."""
    if not handle:
        return ""
    try:
        body = _http_get(f"https://soundcloud.com/{handle}")
        name = _regex_any(body, (
            r'"username"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'<title>\s*([^|<]+?)\s*[|<]',   # fallback: "Name | Free Listening on SoundCloud"
        ))
        if name:
            return name.replace("\\\"", '"').replace("\\/", "/").strip()
        return ""
    except Exception:
        return ""


def _instagram_fetch(handle: str) -> tuple[str, str, str]:
    """Fetch an Instagram profile ONCE. Returns (exists, display_name, bio).

    v0.6.5: consolidates _instagram_check/_display_name/_bio, which each
    re-fetched the same page (up to 3 fetches per registration) — Instagram
    rate-limits aggressively (429), so the re-fetch lottery made claimed
    IG sources randomly fail their name-bind. Single fetch + parsed fields.
    """
    if not handle:
        return "", "", ""
    try:
        body = _http_get(f"https://www.instagram.com/{handle}/")
        if "Page Not Found" in body or "Sorry, this page" in body:
            return "", "", ""
        # display name: og:title ("Name (@handle) • Instagram …") or fullName
        display = _regex_any(body, (
            r'<meta property="og:title"\s+content="([^"]+)"',
            r'"full_name"\s*:\s*"((?:[^"\\]|\\.)*)"',
        ))
        if display:
            display = display.split("(@")[0].replace("\\u0026", "&").strip()
            for suffix in ("• Instagram photos and videos", "• Instagram"):
                if display.endswith(suffix):
                    display = display[: -len(suffix)].strip()
        # bio: og:description
        bio = _regex_any(body, (
            r'<meta property="og:description"\s+content="([^"]+)"',
        ))
        return handle, display or "", bio or ""
    except Exception:
        return "", "", ""


def _regex_any(body: str, patterns: tuple[str, ...]) -> str:
    """Return the first regex match group 1 across several patterns."""
    import re
    for p in patterns:
        m = re.search(p, body)
        if m and m.group(1):
            return m.group(1)
    return ""


def _ipi_checksum_valid(raw: str | None) -> bool:
    """Validate an IPI name number via the CISAC mod-101 checksum.

    IPI name numbers are 11 digits: 9 base digits + 2 checksum digits. Total =
    sum(digit[i] * (10 - i) for the first 9) mod 101; if nonzero, checksum =
    (101 - total) % 100. Verified against canonical examples
    (01234567846, 00123456790 are valid; a random 11-digit is not).
    """
    d = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(d) != 11:
        return False
    total = 0
    for i in range(9):
        total += int(d[i]) * (10 - i)
    total %= 101
    if total != 0:
        total = (101 - total) % 100
    return f"{total:02d}" == d[-2:]


def _tiktok_name(handle: str) -> str:
    """Extract the profile display name from a TikTok page's embedded JSON."""
    if not handle:
        return ""
    try:
        body = _http_get(f"https://www.tiktok.com/@{handle}")
        # Use the __UNIVERSAL_DATA / __NEXT_DATA JSON; grab nickname or uniqueId
        nm = _regex_any(body, (
            r'"nickname"\s*:\s*"([^"]{1,80})"',
            r'"uniqueId"\s*:\s*"([^"]{1,80})"',
            r'<meta content="([^"]{1,80})" property="og:title"',
        ))
        if nm and nm.lower().strip() not in ("", "tiktok"):
            return nm
        return ""
    except Exception:
        return ""


def _page_exists(url: str) -> bool:
    """Return True if a public URL returns HTTP 200 (existence check)."""
    if not url:
        return False
    try:
        body = _http_get(url)
        # some sites return 200 with a 404 body for unknown resources
        if "404" in body[:4000].lower() or "page not found" in body[:4000].lower():
            return False
        return bool(body)
    except Exception:
        return False


def _site_crossrefs(url: str, name: str) -> bool:
    """Best-effort: does a personal website page reference the artist name?"""
    if not url or not name:
        return False
    try:
        body = _http_get(url).lower()
        return bool(body) and name.lower() in body
    except Exception:
        return False


def _verify_claimed_source(
    source_type: str, handle: str, artist_name: str,
    spotify_token: str, lastfm_key: str,
) -> bool:
    """Verify a single DISCO-style claimed source against the artist name.

    Dispatches on the DISCO 13-enum. A source only counts as a match when it
    independently resolves AND binds to the claimed artist identity:
      - Spotify: search returns the same artist id as the claimed URL/id
      - Apple Music: artist resolves and the matched name is >= 3 chars
      - Bandcamp: page exists AND the parsed page name overlaps the claim
      - Last.fm: the claimed user has scrobble history for this artist
      - TikTok: page's embedded display name overlaps the claim (best-effort)
      - Tidal / Facebook: HTTP existence (their APIs are closed)
      - SoundCloud / Instagram: HTTP existence only (name binding needs
        private APIs; documented limitation)
      - website: page exists AND mentions the claimed name
      - IPI: CISAC mod-101 checksum on the 11-digit number
      - Twitter / YouTube: claim-only (no public name-check without API keys)

    Returns True only when the source independently resolves to the claimed
    artist name.
    """
    if not handle or not artist_name:
        return False
    st = source_type.lower().strip()
    handle = str(handle or "")   # v0.6.2: CLI/JSON callers may send int IDs

    # Spotify: handle is the artist ID (or a full URL). Search resolves the ID.
    if st in ("spotify_url", "spotify"):
        sid = _spotify_artist_id(handle)
        if not sid:
            return False
        # confirm the artist page exists via the Spotify search API
        sp = _spotify_search(artist_name, spotify_token)
        return bool(sp and sp.get("id") == sid)
    if st in ("apple_music_url", "apple_music", "apple"):
        # artist resolves to a real Apple Music artist page; a short claimed
        # name (e.g. "A") is too weak to pin the artist, so require >= 3 chars
        if len(artist_name.strip()) < 3:
            return False
        # If the handle is a bare numeric Apple Music artist ID, confirm it
        # directly; otherwise search by name. (v0.6.1: coerce — JSON/CLI
        # callers may deliver the ID as an int.)
        handle = str(handle)
        if handle.isdigit() and len(handle) >= 6:
            url = f"https://itunes.apple.com/lookup?id={handle}&entity=musicArtist&limit=1"
            data = _http_get_json(url)
            results = (data or {}).get("results", [])
            if not results or results[0].get("wrapperType") != "artist":
                return False
            return _name_token_overlap(
                results[0].get("artistName", ""), artist_name
            ) >= 0.5
        artist_id, _ = _apple_music_search(artist_name, "")
        return bool(artist_id)
    if st in ("bandcamp_url", "bandcamp"):
        h = _bandcamp_handle(handle)
        bch, real_name, _ = _bandcamp_check(h)
        if not bch:
            return False
        # bandcamp_check already parsed the page name — bind it to the claim
        return _name_token_overlap(real_name, artist_name) >= 0.5
    if st in ("soundcloud_url", "soundcloud"):
        # v0.6.1: name-bind via the profile's display name. Existence-only
        # matching let attacker-owned pages pass as "verified source" for
        # ANY claimed artist (audit F1). Display name must overlap the
        # claimed name (same bar as Bandcamp/TikTok).
        h = handle.rstrip("/").split("/")[-1].split("?")[0]
        sh, _, _ = _soundcloud_check(h)
        if not sh:
            return False  # page fetch failed — no existence proof at all
        display = _soundcloud_display_name(h)
        if _name_token_overlap(display, artist_name) >= 0.5:
            return True
        # Usernames often aren't the artist name ("user823745", nicknames,
        # label prefixes) — accept a bio that names the artist, or the
        # handle itself (normalized: 'demuja' == 'Demuja').
        bio = _soundcloud_bio(h)
        if _name_token_overlap(bio, artist_name) >= 0.5:
            return True
        return _name_token_overlap(h, artist_name) >= 0.5
    if st in ("instagram_handle", "instagram"):
        # v0.6.5: single fetch, then name-bind. Binding candidates: display
        # name, bio, AND the handle itself — usernames are often the only
        # artist-identifying part ('_interfluve' → 'interfluve').
        h = handle.rstrip("/").split("/")[-1]
        exists, display, bio = _instagram_fetch(h)
        if not exists:
            return False
        if _name_token_overlap(display, artist_name) >= 0.5:
            return True
        if _name_token_overlap(bio, artist_name) >= 0.5:
            return True
        # Username as binding candidate (normalized, underscore stripped)
        return _name_token_overlap(h, artist_name) >= 0.5
    if st in ("lastfm_url", "lastfm", "lastfm_user"):
        # Last.fm user is the claimed handle; scrobbles of THIS artist by
        # that user is a genuine listener/ownership signal (needs the key).
        # at least some scrobble history binds the user to the artist
        return _lastfm_scrobbles(artist_name, handle, lastfm_key) > 0
    if st in ("tiktok_handle", "tiktok"):
        h = handle.rstrip("/").split("/")[-1].lstrip("@")
        if not h:
            return False
        # bind via the page's embedded display name (best-effort)
        nm = _tiktok_name(h)
        if not nm:
            return False
        return _name_token_overlap(nm, artist_name) >= 0.5
    if st in ("tidal_music_url", "tidal"):
        # Tidal has no public API; an artist URL resolving counts
        return _page_exists(handle)
    if st in ("facebook_url", "facebook"):
        # Facebook HTML isn't parseable without login; existence only
        return _page_exists(handle)
    if st in ("website_url", "website", "personal_url"):
        # personal site exists AND mentions the claimed name
        return _site_crossrefs(handle, artist_name)
    if st in ("ipi_number", "ipi"):
        # IPI base/name number: validate the CISAC mod-101 checksum
        return _ipi_checksum_valid(handle)
    if st in ("musicbrainz_url", "musicbrainz", "mb"):
        # MusicBrainz artist MBID: fetch the artist and confirm the
        # resolved name overlaps the claimed artist identity.
        mbid = handle.rstrip("/").split("/")[-1] if "/" in handle else handle
        if not mbid:
            return False
        data = {}
        for attempt in range(2):   # MB polices ~1 req/s — one spaced retry
            try:
                data = _http_get_json(f"{MUSICBRAINZ_ARTIST_URL}{mbid}?fmt=json")
                if data:
                    break
            except Exception:
                pass
            import time
            time.sleep(1.2)
        resolved = (data or {}).get("name", "")
        if not resolved:
            return False
        return _name_token_overlap(resolved, artist_name) >= 0.5

    # Source with no verifiable name cross-check yet — claim-only. Layer 2
    # leaves Twitter/YouTube here (no public name-check without API keys).
    return False


def _bandcamp_handle(raw: str) -> str:
    """Extract a bandcamp handle from a URL or bare handle."""
    if ".bandcamp.com" in raw:
        return raw.split("//")[-1].split(".")[0]
    return raw.split("/")[0]


def _normalize_bandcamp(raw: str) -> str:
    """Normalize user input to a bare bandcamp handle.

    Accepts either a full URL ("https://mindex.bandcamp.com/") or a
    bare handle ("mindex"). Returns the bare handle.
    """
    if not raw:
        return ""
    if ".bandcamp.com" in raw:
        return raw.split("://")[-1].split(".bandcamp.com")[0].rstrip("/")
    return raw.split("/")[0].strip()


def _normalize_soundcloud(raw: str) -> str:
    """Normalize a SoundCloud input to a bare handle."""
    if not raw:
        return ""
    if "soundcloud.com/" in raw:
        return raw.split("soundcloud.com/")[-1].rstrip("/").split("?")[0]
    return raw.lstrip("@").rstrip("/").split("?")[0]


def _normalize_instagram(raw: str) -> str:
    """Normalize an Instagram input to a bare handle."""
    if not raw:
        return ""
    if "instagram.com/" in raw:
        return raw.split("instagram.com/")[-1].rstrip("/").split("?")[0]
    return raw.lstrip("@").rstrip("/").split("?")[0]


def _spotify_artist_id(raw: str) -> str:
    """Extract a Spotify artist ID from a URL or return a bare ID as-is."""
    if "open.spotify.com/artist/" in raw:
        return raw.split("/artist/")[-1].split("?")[0]
    # bare 22-char base62 ID
    if raw and len(raw) == 22:
        return raw
    return ""


def _lastfm_resolve_artist(artist: str, lastfm_key: "str | list") -> str:
    """Resolve a claimed artist name to Last.fm's canonical name via artist.search.

    `artist.getInfo` requires the exact canonical name — a raw user-typed
    "fred again.." yields 0 userplaycount even for a real fan. The search
    endpoint returns the top match's canonical name + MBID, which we then
    feed back into getInfo. Requires the API key; empty key → "" (no
    signal, caller treats as 0). `lastfm_key` may be a list (rate-limit
    pool): rotates to the next key on error 29 (rate limit) / 10 (invalid).
    """
    if not artist:
        return ""
    keys = lastfm_key if isinstance(lastfm_key, (list, tuple)) else [lastfm_key]
    keys = [k for k in keys if k]
    if not keys:
        return ""
    for api_key in keys:
        try:
            url = (
                f"https://ws.audioscrobbler.com/2.0/?method=artist.search"
                f"&artist={artist}&limit=1&api_key={api_key}&format=json"
            )
            data = _http_get_json(url)
            if not data:
                continue
            err = data.get("error")
            if err == 29 or err == 10:  # rate-limited / invalid key → rotate
                continue
            matches = (data or {}).get("results", {}).get("artistmatches", {}).get("artist", [])
            if not matches:
                return ""
            name = matches[0].get("name", "")
            mbid = matches[0].get("mbid", "")
            # strong binding: MBID present AND the match is actually the claimed
            # artist. Search ranks by popularity — "Interfluve" returns
            # "Aliyah's Interlude" (has an MBID, zero relation). Trusting any
            # MBID silently queries a stranger's scrobble history → always 0.
            if name and mbid and _name_token_overlap(name, artist) >= 0.5:
                return name
            # wrong-artist match: fall back to direct getInfo with the raw
            # claimed name — canonical name comes back even when search
            # ranks a different artist first
            info = _http_get_json(
                f"https://ws.audioscrobbler.com/2.0/?method=artist.getInfo"
                f"&artist={artist}&api_key={api_key}&format=json"
            )
            canon = (info or {}).get("artist", {}).get("name", "")
            if canon and _name_token_overlap(canon, artist) >= 0.5:
                return canon
            return ""
        except Exception:
            continue
    return ""


def _lastfm_scrobbles(artist: str, lastfm_user: str, lastfm_key: "str | list") -> int:
    """Return scrobble count for an artist in a Last.fm user's history.

    `lastfm_key` may be a single key or a list of keys (rate-limit pool):
    on error 29 (rate limit) or 10 (invalid key) the pool rotates to the
    next key. Returns 0 when every key fails or no key is present.
    """
    if not lastfm_user or not artist:
        return 0
    keys = lastfm_key if isinstance(lastfm_key, (list, tuple)) else [lastfm_key]
    keys = [k for k in keys if k]
    if not keys:
        return 0
    # resolve to the canonical name first — see _lastfm_resolve_artist
    canonical = _lastfm_resolve_artist(artist, keys[0])
    if not canonical:
        return 0
    for api_key in keys:
        url = (
            f"https://ws.audioscrobbler.com/2.0/?method=artist.getInfo"
            f"&artist={canonical}&username={lastfm_user}&api_key={api_key}&format=json"
        )
        data = _http_get_json(url)
        try:
            err = data.get("error")
            if err == 29 or err == 10:  # rate-limited / invalid key → rotate
                continue
            return int(data.get("artist", {}).get("stats", {}).get("userplaycount", 0))
        except Exception:
            continue
    return 0


# ─── Tier 2.6 — ownership proofs (artist-controlled tokens) ───────────────

def _token_in_text(text: str, token: str) -> bool:
    """Case-sensitive exact containment of the full ALVERIFY token.

    Case-sensitive on purpose: the token is a random base32-ish string,
    so demanding exact form kills case-folding sybil variants like
    alverify-xxxx masquerading as the real claim.
    """
    if not text or not token:
        return False
    return token in text


def _soundcloud_bio(handle: str) -> str:
    """Fetch the profile HTML and extract the bio/description text.

    SoundCloud embeds the profile JSON (including `description`) in the
    page's __NEXT_DATA__ / og:description meta. We grep both, plus the
    plain body as a last resort — the token is distinctive enough that
    any of the three carrying it is proof.
    """
    if not handle:
        return ""
    try:
        body = _http_get(f"https://soundcloud.com/{handle}")
        bio = _regex_any(body, (
            # Embedded user JSON: description immediately followed by
            # followers_count (verified against live page 2026-09-13 — the
            # generic "Listen to X | SoundCloud is an audio platform..." og
            # meta description is boilerplate and must NOT be the match).
            r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"followers_count"',
            r'"biography"\s*:\s*"((?:[^"\\]|\\.)*)"',
        ))
        # JSON-escaped bio: unescape \" and \/ so the token matches
        return bio.replace('\\n', '\n').replace('\\"', '"').replace('\\/', '/')
    except Exception:
        return ""


def _lastfm_profile_and_scrobbles(handle: str, lastfm_key: "str | list") -> tuple[str, int]:
    """Fetch a Last.fm user page: returns (bio_html, lifetime_scrobbles).

    Lifetime scrobble count comes from the user profile page — it's the
    account-maturity signal: a brand new sybil account has ~0 scrobbles
    regardless of what their bio says.

    Parsing (validated against live page 2026-09-12): the count lives in
    a bare `<p>` right after the `Scrobbles` header-metadata-title, e.g.
    `<h4 ...>Scrobbles</h4> <p>151,481</p>`. The old "N scrobbles" text
    pattern is a trap: the page also renders an *average per day* tooltip
    ("an average of 17 scrobbles per day!") that would match first and
    report 17 instead of 151,481. We anchor on the header and grab the
    next number, and verify against the `Scrobbles` label specifically.
    """
    if not handle:
        return "", 0
    try:
        import re  # GenVM: keep imports at call time (matches _regex_first)
        body = _http_get(f"https://www.last.fm/user/{handle}")
        scrobbles = 0
        # Anchor: <h4 ...>Scrobbles</h4> <div ...> <p title="avg/day tooltip">
        # <a href="/user/{handle}/library">151,481</a>. The count is the
        # number inside the library link that follows the Scrobbles label.
        # DO NOT match "N scrobbles" generally — the tooltip title renders
        # "an average of 17 scrobbles per day!" and would match first.
        m = re.search(
            r'header-metadata-title">\s*Scrobbles\s*</h4>(.*?)'
            r'library"\s*>\s*([\d,]{4,})\s*</a>',
            body, re.S,
        )
        if m and m.group(2):
            try:
                scrobbles = int(m.group(2).replace(",", ""))
            except ValueError:
                scrobbles = 0
        return body, scrobbles
    except Exception:
        return "", 0


def _bandcamp_about(subdomain: str) -> str:
    """Fetch a Bandcamp artist page's about/disco text.

    Bandcamp embeds the artist bio in the page's og:description and in
    the `band_data` JSON blob. The artist edits this in their Bandcamp
    profile ("Edit profile" → bio), so a token there is proof of control.
    """
    if not subdomain:
        return ""
    try:
        body = _http_get(f"https://{subdomain}.bandcamp.com")
        about = _regex_any(body, (
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            r'"about"\s*:\s*"((?:[^"\\]|\\.)*)"',
            r'<p class="artists-bio-text">([^<]+)</p>',
        ))
        return about.replace('\\"', '"').replace('\\/', '/')
    except Exception:
        return ""


def _youtube_description(raw: str) -> str:
    """Fetch a YouTube channel's description text.

    `raw` is a handle (@name), channel URL, or channel ID. Channel pages
    are JS-heavy, but the description is present in the initial HTML
    inside ytInitialData and in the og:description meta — the meta is
    the stable one.
    """
    if not raw:
        return ""
    h = raw.strip().lstrip("@").replace("https://youtube.com/", "").replace("https://www.youtube.com/", "")
    h = h.split("/channel/")[-1].split("/c/")[-1].split("/@")[-1].rstrip("/")
    if not h:
        return ""
    try:
        if h.startswith("UC"):
            url = f"https://www.youtube.com/channel/{h}"
        else:
            url = f"https://www.youtube.com/@{h}"
        body = _http_get(url)
        desc = _regex_any(body, (
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            r'"description":\s*\{\s*"simpleText":\s*"((?:[^"\\]|\\.)*)"',
        ))
        return desc.replace('\\n', '\n').replace('\\"', '"').replace('\\/', '/')
    except Exception:
        return ""


# ─── Tier 5 (wallet-derived) ──────────────────────────────────────────────

def _wallet_age_days(wallet: str, etherscan_key: str) -> int:
    """Compute wallet age in days via Etherscan.

    Returns the number of whole days between the wallet's first on-chain
    transaction and the current transaction's timestamp. Uses
    `gl.message_raw['datetime']` (consensus-safe) for the "now" side.
    If `etherscan_key` is empty, returns 0 (no signal) so the wallet-age
    factor never auto-passes the 90-day threshold.
    """
    if not wallet or not etherscan_key:
        return 0
    api_key = etherscan_key
    url = (
        f"{ETHERSCAN_TX_URL}?module=account&action=txlist&address={wallet}"
        f"&startblock=0&endblock=99999999&sort=asc&apikey={api_key}"
    )
    data = _http_get_json(url)
    try:
        first_tx = data.get("result", [{}])[0]
        ts = int(first_tx.get("timeStamp", "0"))
        if not ts:
            return 0
        now = int(datetime.fromisoformat(gl.message_raw['datetime']).timestamp())
        if now <= ts:
            return 0
        return (now - ts) // 86400
    except Exception:
        return 0


def _ens_data(wallet: str) -> tuple[str, bool]:
    """Reverse-resolve an ENS name for a wallet."""
    if not wallet:
        return "", False
    try:
        data = _http_get_json(f"{ENSDATA_URL}{wallet}")
        name = data.get("name", "")
        return name, False  # ens_matches_artist set by caller
    except Exception:
        return "", False


def _farcaster_fname(wallet: str) -> str:
    """Look up Farcaster fname for a wallet."""
    if not wallet:
        return ""
    try:
        data = _http_get_json(f"{FARCASTER_USER_URL}?address={wallet}")
        return data.get("user", {}).get("username", "")
    except Exception:
        return ""


# ─── Scoring ──────────────────────────────────────────────────────────────

def _ev_get(ev, key, default=None):
    """Read a field from an Evidence object OR a dict (consensus boundary
    can deserialise the leader's Evidence as a plain dict, so we accept both)."""
    if isinstance(ev, dict):
        v = ev.get(key, default)
        return default if v is None else v
    return getattr(ev, key, default)


def _score_evidence(ev, claimed_name: str) -> int:
    """Compute the deterministic score from an Evidence struct.

    Accepts either an Evidence instance (leader) or a dict (post-consensus
    deserialised payload). The cross-process consensus boundary serialises
    the leader's return to JSON; depending on the GenVM version, the
    receiving side may see it as a dict or as the original Evidence
    wrapper. Supporting both keeps the scoring deterministic.

    Returns a Python int [0, 100]. The int is converted to u256 by the
    caller when written to storage.
    """
    score = 0

    # Tier 1 (max 45)
    if _ev_get(ev, "acoustid_matched", False):
        score += W_ACOUSTID
    if len(_ev_get(ev, "isrc_codes", []) or []) > 0:
        score += W_ISRC
    # Spotify: 10 if verified OR name-bound (top hit matches claimed name).
    # popularity/followers thresholds are kept for extended-quota keys that
    # still get those fields (Feb-2026 API removed them for dev-mode apps).
    sp_id = _ev_get(ev, "spotify_artist_id", "")
    if sp_id and (
        _ev_get(ev, "spotify_verified", False)
        or _ev_get(ev, "spotify_name_matched", False)
        or (int(_ev_get(ev, "spotify_popularity", 0)) >= 20
            and int(_ev_get(ev, "spotify_followers", 0)) >= 1000)
    ):
        score += W_SPOTIFY
    if _ev_get(ev, "apple_music_track_present", False):
        score += W_APPLE_MUSIC

    # Tier 2 (max 20)
    if _ev_get(ev, "bandcamp_handle", ""):
        score += W_BANDCAMP
    sc_handle = _ev_get(ev, "soundcloud_handle", "")
    if sc_handle and (_ev_get(ev, "soundcloud_verified", False) or int(_ev_get(ev, "soundcloud_followers", 0)) >= 100):
        score += W_SOUNDCLOUD
    if _ev_get(ev, "instagram_handle", ""):
        score += W_INSTAGRAM
    if int(_ev_get(ev, "lastfm_scrobble_count", 0)) >= 100:
        score += W_LASTFM

    # Tier 2.5 — two-source verification (DISCO parity)
    m = int(_ev_get(ev, "verification_match_count", 0))
    if m >= 2:
        score += W_TWO_SOURCE_MATCH
    elif m == 1:
        score += W_SINGLE_SOURCE_MATCH

    # Tier 2.6 — ownership proofs (max W_OWNERSHIP_PROOF × W_OWNERSHIP_CAP)
    ownership_count = sum(1 for k in (
        "ownership_proof_soundcloud",
        "ownership_proof_lastfm",
        "ownership_proof_bandcamp",
        "ownership_proof_youtube",
    ) if _ev_get(ev, k, False))
    score += W_OWNERSHIP_PROOF * min(ownership_count, W_OWNERSHIP_CAP)

    # Tier 5 (max 10)
    if int(_ev_get(ev, "wallet_age_days", 0)) >= 90:
        score += W_WALLET_AGE
    if _ev_get(ev, "ens_matches_artist", False) or _ev_get(ev, "farcaster_fname", ""):
        score += W_WALLET_NAME

    # Tier 3 (LLM, ±5)
    bounded_adjustment = max(-W_LLM_ADJUSTMENT_RANGE, min(W_LLM_ADJUSTMENT_RANGE, int(_ev_get(ev, "press_narrative_score", 0))))
    score += bounded_adjustment

    # Tier 3b — LLM identity guard. When the LLM judges that the collected
    # sources describe a DIFFERENT entity than the claimed name, the score is
    # capped below the verification threshold: an artist whose evidence is
    # "real but someone else's" must never reach VRFD. Absent/True (old
    # receipts, stub environments) = unchanged scoring.
    if _ev_get(ev, "llm_identity_match", True) is False:
        score = min(score, int(DISPUTE_UPHOLD_THRESHOLD) - 1)

    return max(0, min(100, score))


def _llm_identity_match(name: str, sources_summary: str) -> bool:
    """LLM identity guard: do the collected sources describe the SAME
    person/band as the claimed artist name, or a different entity?

    Catches wrong-entity verifications that token-overlap checks let
    through ("Stain" -> "Blood Stain Child", "Max Cooper" the producer vs
    the entomologist, "Burial" the practice). Runs in a nondet block like
    every LLM call; validators receive the leader's boolean via calldata
    (no re-fetch — same 'verify determinism' pattern as the rest of
    evidence). Prompt v1: pinned wording, change requires a contract
    version bump so all validators judge identically.
    """
    prompt = (
        f"You are checking IDENTITY CONSISTENCY for an on-chain music "
        f"provenance registry.\n"
        f"Claimed artist name: '{name}'.\n\n"
        f"Evidence collected from public sources:\n{sources_summary}\n\n"
        f"Question: do these sources consistently refer to the SAME "
        f"person/band as '{name}' (a real music artist), or do any of "
        f"them appear to describe a DIFFERENT entity that merely shares "
        f"words with the name (e.g. a disambiguation page, a different "
        f"person with the same name, a non-music subject)?\n\n"
        f"Respond with ONLY one word: SAME_ENTITY or DIFFERENT_ENTITY."
    )
    try:
        raw = gl.nondet.exec_prompt(prompt).strip().upper()
        return "SAME_ENTITY" in raw and "DIFFERENT" not in raw
    except Exception:
        # LLM unavailable: fail OPEN (absent field behaves the same —
        # this guard is additive defense, not a hard dependency)
        return True


def _llm_qualitative_adjustment(name: str, sources_summary: str) -> int:
    """LLM call: judge whether the sources tell a consistent narrative.
    Returns -5 to +5. The leader AND validator both call this; the validator
    re-derives sources independently before calling."""
    prompt = (
        f"You are evaluating whether multiple independent web sources "
        f"tell a consistent biographical narrative for the music artist "
        f"'{name}'.\n\n"
        f"Sources summary:\n{sources_summary}\n\n"
        f"Return a single integer from -5 to +5:\n"
        f"  +5: sources clearly describe a real, consistent artist with "
        f"press, label relationships, and a coherent story\n"
        f"   0: sources are sparse or generic, no clear narrative either way\n"
        f"  -5: sources contradict each other or describe someone who is "
        f"clearly not a music artist (e.g., wrong person, fabricated bio)\n\n"
        f"Respond with ONLY the integer."
    )
    raw = gl.nondet.exec_prompt(prompt)
    try:
        return int(raw.strip().split()[0])
    except Exception:
        return 0


# ─── Helper regex ─────────────────────────────────────────────────────────

def _regex_first(body: str, pattern: str) -> str:
    """Return the first regex match group 1 from a body, or empty string."""
    import re  # only at call time to avoid top-of-file overhead
    m = re.search(pattern, body)
    return m.group(1) if m else ""


def _profile_clusters_overlap(stored: dict, claimed: dict) -> bool:
    """v0.7.0 — per-platform same-profile rule for identity rotation.

    reverify() must re-prove control of a profile that was ALREADY part of
    the original verified evidence — otherwise an attacker could hijack a
    name by squatting the handle on a platform the victim never used
    (e.g. youtube.com/@burial) and pasting their own fresh token there.

    A claimed proof channel counts ONLY if its handle matches the handle
    stored for the SAME platform in the original evidence:
      - bandcamp  -> stored bandcamp_handle
      - soundcloud -> stored soundcloud_handle
      - instagram -> stored instagram_handle
    Platforms the contract never stored a handle for (last.fm username,
    youtube channel — only proof booleans are kept) can still match via a
    stored verification source whose name contains the platform
    (verification_source_N, e.g. "lastfm_url"/"youtube_url"); otherwise a
    claim on those channels can never be the recovery proof.

    `stored` is the parsed evidence dict from the artist record;
    `claimed` is the reverify ownership_proofs dict {platform: handle}.
    """
    import re as _re

    def _norm(h: str) -> str:
        try:
            return str(h).strip().lower().rstrip("/")
        except Exception:
            return ""

    NORMALIZERS = {
        "bandcamp": _normalize_bandcamp,
        "soundcloud": _normalize_soundcloud,
        "instagram": _normalize_instagram,
    }

    def _forms(h: str, platform: str) -> set:
        forms = {_norm(h)}
        nz = NORMALIZERS.get(platform)
        if nz is not None:
            try:
                n = _norm(nz(str(h)))
                if n:
                    forms.add(n)
            except Exception:
                pass
        m = _re.search(r"/([^/]+)/?$", str(h))
        if m:
            tail = _norm(m.group(1))
            if tail:
                forms.add(tail)
        return forms

    # Stored handles, keyed by platform.
    stored_by_platform: dict = {}
    if isinstance(stored, dict):
        for key, plat in (
            ("bandcamp_handle", "bandcamp"),
            ("soundcloud_handle", "soundcloud"),
            ("instagram_handle", "instagram"),
        ):
            if stored.get(key):
                stored_by_platform.setdefault(plat, []).append(stored[key])
        # verification sources: the source NAME tells us the platform
        for n in (1, 2):
            src = str(stored.get(f"verification_source_{n}") or "").lower()
            h = stored.get(f"verification_handle_{n}") or ""
            if not h:
                continue
            for plat in ("bandcamp", "soundcloud", "instagram", "lastfm", "youtube"):
                if plat in src:
                    stored_by_platform.setdefault(plat, []).append(h)
                    break

    if not isinstance(claimed, dict):
        return False
    for plat, h in claimed.items():
        if not h:
            continue
        p = str(plat).lower()
        if p not in stored_by_platform:
            continue
        claimed_forms = _forms(h, p)
        for stored_handle in stored_by_platform[p]:
            if claimed_forms & _forms(stored_handle, p):
                return True
    return False


# ─── Contract ──────────────────────────────────────────────────────────────

class ProvenanceRegistry(gl.Contract):
    artists: TreeMap[Address, Artist]
    releases: TreeMap[bytes, Release]
    disputes: TreeMap[bytes, Dispute]
    identity_score: TreeMap[Address, u256]
    identity_count: TreeMap[Address, u256]
    artist_releases: TreeMap[Address, DynArray[bytes]]
    # Identity index — one artist = one wallet. Maps the stable ownership
    # token (and canonical name) to the wallet that first verified, so a
    # second wallet re-validating the same person is detected and rejected.
    verified_by_token: TreeMap[str, str]   # ALVERIFY token -> wallet addr
    verified_by_name: TreeMap[str, str]    # canonical (lowercase) name -> wallet addr
    # v0.7.0 — revoked wallets (identity rotation). reverify() moves the
    # identity to a new wallet and marks the old one here. Views treat a
    # revoked wallet as not-verified (the identity lives on elsewhere).
    # Keys are lowercase wallet strings (TreeMap can't be iterated, so a
    # membership marker is the only GenVM-safe revocation signal).
    revoked_wallets: TreeMap[str, bool]

    # API credentials. Set by `set_api_keys` before the first
    # `register_artist` call. All four are read inside `run_nondet_unsafe`
    # by the leader, then passed to the module-level API helpers.
    acoustid_key: str
    spotify_token: str
    lastfm_key: str
    etherscan_key: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_client_pairs: str  # JSON: [[client_id, secret], ...] — rate-limit pool (str is storage-safe; bare list is not)
    lastfm_key_pool: str       # JSON: [key, ...] — MUST be a class-level annotation for GenVM to allocate a storage slot (this line was missing → writes executed but never persisted)

    def __init__(self):
        """Schema constructor (required by GenVM). API keys default to
        empty so reads before `set_api_keys` fail quiet (no signal)."""
        self.acoustid_key = ""
        self.spotify_token = ""
        self.lastfm_key = ""
        self.lastfm_key_pool: str = ""   # JSON array of keys — str is storage-safe
        self.etherscan_key = ""
        self.spotify_client_id = ""
        self.spotify_client_secret = ""
        self.spotify_client_pairs = ""   # JSON: [[client_id, secret], ...]

    def _now(self) -> int:
        """Consensus-safe transaction timestamp (unix seconds).

        Reads the transaction datetime from `gl.message_raw` (ISO 8601
        string) and converts to unix seconds. Every validator re-executing
        the same transaction sees the same value, so this is safe to use
        outside `run_nondet_unsafe` blocks for storage writes like
        `verified_at`, `anchored_at`, and `filed_at`.
        """
        return int(datetime.fromisoformat(gl.message_raw['datetime']).timestamp())

    def _sender(self) -> Address:
        """Caller wallet address, exposed by GenVM."""
        return gl.message.sender_address

    def _is_revoked(self, wallet) -> bool:
        """True only while the wallet's record is DEAD.

        reverify tombstones the old wallet (score-0 record) and sets the
        revoked_wallets marker. The marker alone must NOT shade views: a
        later legitimate operation (recovery INTO this wallet, or a fresh
        registration) writes a LIVE record here, and the wallet is then a
        normal active wallet again. A wallet is revoked iff it is marked
        AND currently holds no live identity (TreeMap can't be deleted, so
        the marker is permanent but the DERIVED state follows the record).
        """
        key = str(wallet).lower()
        if key not in self.revoked_wallets:
            return False
        try:
            rec = self.artists.get(Address(wallet))
        except Exception:
            rec = None
        return rec is None or int(rec.score) <= 0

    @gl.public.write
    def set_api_keys(
        self,
        acoustid_key: str,
        spotify_token: str,
        lastfm_key: str,
        etherscan_key: str,
        spotify_client_id: str = "",
        spotify_client_secret: str = "",
    ) -> str:
        """Set the upstream API credentials used by `register_artist`.

        This is unguarded for testnet simplicity. For production, gate it
        behind a stored admin address and only allow the deployer to
        call it. The keys are read inside `run_nondet_unsafe` by the
        leader, so all four must be set before the first
        `register_artist` call.

        Pass empty strings for keys you don't have; the corresponding
        evidence field will then return its default (no signal).

        `spotify_client_id`/`spotify_client_secret` are optional: when a
        spotify_token is not provided, the leader mints a short-lived
        bearer via the client-credentials flow (no OAuth consent).
        """
        self.acoustid_key = acoustid_key
        self.spotify_token = spotify_token
        self.spotify_client_id = spotify_client_id
        self.spotify_client_secret = spotify_client_secret
        self.lastfm_key = lastfm_key
        self.etherscan_key = etherscan_key
        return "API keys set"

    @gl.public.write
    def set_lastfm_key_pool(self, keys: list) -> str:
        """Seed/rotate the Last.fm key pool (rate-limit failover).

        Each key is used round-robin; on error 29 (rate limit) or 10
        (invalid/revoked key) the resolver advances to the next key.
        Empty list clears the pool.
        """
        cleaned = []
        if isinstance(keys, str):
            # CLI sometimes delivers a flat JSON array as a raw string
            # (arg parsing quirk). Accept it either way.
            try:
                parsed = json.loads(keys)
                if isinstance(parsed, list):
                    keys = parsed
                else:
                    keys = [keys]
            except Exception:
                keys = [keys]
        cleaned = [k for k in keys if isinstance(k, str) and k]
        self.lastfm_key_pool = json.dumps(cleaned)
        return f"Last.fm key pool set ({len(cleaned)} keys)"

    @gl.public.view
    def get_lastfm_pool_size(self) -> int:
        try:
            return len(json.loads(self.lastfm_key_pool or "[]"))
        except Exception:
            return 0

    def _lastfm_pool_list(self) -> list:
        """Parse the stored JSON pool into a list for the leader."""
        try:
            return json.loads(self.lastfm_key_pool or "[]")
        except Exception:
            return []

    @gl.public.write
    def set_spotify_key_pool(self, pairs: list) -> str:
        """Seed the Spotify client-credentials pool (rate-limit failover).

        Each entry is [client_id, client_secret]. Minting rotates through
        the pool on failure (401/429); the single pair from set_api_keys
        is the fallback when the pool is empty or exhausted.
        """
        cleaned = []
        if isinstance(pairs, str):
            try:
                parsed = json.loads(pairs)
                if isinstance(parsed, list):
                    pairs = parsed
                else:
                    pairs = [pairs]
            except Exception:
                pairs = [pairs]
        cleaned = [
            [str(p[0]), str(p[1])] for p in pairs
            if isinstance(p, (list, tuple)) and len(p) >= 2 and p[0] and p[1]
        ]
        self.spotify_client_pairs = json.dumps(cleaned)
        return f"Spotify key pool set ({len(cleaned)} pairs)"

    @gl.public.view
    def get_spotify_pool_size(self) -> int:
        try:
            return len(json.loads(self.spotify_client_pairs or "[]"))
        except Exception:
            return 0

    def _spotify_pool_list(self) -> list:
        """Parse the stored JSON pool into a list for the leader."""
        try:
            return json.loads(self.spotify_client_pairs or "[]")
        except Exception:
            return []

    # ─── Identity verification ─────────────────────────────────────────────

    @gl.public.view
    def get_verified_by_token(self, token: str) -> dict:
        """Given an ALVERIFY token, return the wallet that validated with it
        (and whether that artist is still certified). Empty result = fresh."""
        owner = self.verified_by_token[token] if token in self.verified_by_token else ""
        if not owner:
            return {"found": False}
        artist = self.artists.get(owner)
        revoked = self._is_revoked(owner)
        return {
            "found": True,
            "wallet": owner,
            "name": artist.name if artist else "",
            "score": int(artist.score) if artist else 0,
            "verified": bool(not revoked and artist and artist.score >= VERIFICATION_THRESHOLD and artist.verified_at > u256(0)),
            "revoked": revoked,
            "verified_at": int(artist.verified_at) if artist else 0,
        }

    @gl.public.view
    def get_verified_by_name(self, name: str) -> dict:
        """Given an artist name, return the wallet that validated it (first
        registrant wins; reverify re-points it). Empty result = the name is free."""
        canon = name.strip().lower()
        owner = self.verified_by_name[canon] if canon in self.verified_by_name else ""
        if not owner:
            return {"found": False}
        artist = self.artists.get(owner)
        revoked = self._is_revoked(owner)
        return {
            "found": True,
            "wallet": owner,
            "name": artist.name if artist else canon,
            "score": int(artist.score) if artist else 0,
            "verified": bool(not revoked and artist and artist.score >= VERIFICATION_THRESHOLD and artist.verified_at > u256(0)),
            "revoked": revoked,
            "verified_at": int(artist.verified_at) if artist else 0,
        }

    @gl.public.write
    def reverify(
        self,
        old_wallet: str,
        name: str,
        ownership_token: str = "",
        ownership_proofs: dict = {},
    ) -> str:
        """Rotate a verified identity to a new wallet (identity ≠ wallet).

        The wallet is a revocable pointer; the verified PROFILE CLUSTER is
        the identity. A verified artist who lost, locked, or got robbed of
        their key calls this from a NEW wallet, pastes a fresh ALVERIFY
        token into the SAME profiles that were bound at registration, and
        the leader re-fetches those profiles to confirm control.

        On consensus the identity record moves (same name, same score, same
        DID, evidence kept):
          - artists[old] deleted; old wallet marked revoked
          - verified_by_name / verified_by_token re-pointed at the new wallet
          - every anchored release re-pointed at the new wallet, so
            is_verified_human() keeps working for the identity

        Refused when: the old wallet isn't a verified artist, the name
        doesn't match the stored identity, the new wallet already holds a
        verified identity (one wallet = one identity), no ownership proof
        can be confirmed, or the proof isn't on a profile that was part of
        the original evidence (attacker-hijack guard).

        The challenge window reuses this exact mechanism — a challenge is
        a triggered contest where both sides re-prove profile control.
        """
        sender = self._sender()
        new_wallet = str(sender)
        old = str(old_wallet)

        # ── Gates (cheap, before any consensus work) ──────────────────────
        if not ownership_token or not ownership_proofs:
            return "Recovery requires an ALVERIFY token pasted into your profiles (ownership_proofs)"
        if ownership_token in self.verified_by_token:
            # Token replay guard: the registration token stays visible in the
            # artist's public profile forever, so it must NOT be a valid
            # recovery credential — anyone could read it off the bio and
            # migrate the identity to their own wallet. Tokens are single-use:
            # recovery is only possible with a token that has never been seen
            # on-chain (the artist pastes it AFTER generating it).
            return "Recovery token already used — generate a FRESH ALVERIFY token (tokens are single-use)"
        if new_wallet.lower() == old.lower():
            return "Already the current wallet for this identity"
        artist = self.artists.get(Address(old))
        if artist is None:
            return "No verified artist on that wallet"
        if int(artist.score) < int(VERIFICATION_THRESHOLD) or int(artist.verified_at) <= 0:
            return "Original wallet is not verified — use register_artist first"
        if _name_token_overlap(name, artist.name) < 0.5:
            return "Name does not match the identity bound to that wallet"
        # Active-identity gate: a REVOKED wallet (score-0 tombstone) is free
        # real estate — only an ACTIVE verified identity on the sender
        # blocks recovery into it.
        existing_new = self.artists.get(sender)
        if existing_new is not None and int(existing_new.score) > 0:
            return "New wallet already holds a verified identity — use a fresh wallet"

        # Stored evidence — the profiles the identity was verified with.
        # The recovery proof must land on one of THESE SAME platforms
        # (per-platform same-profile rule), not on an arbitrary new page
        # or a handle squatted on a platform the artist never used.
        stored_evidence = {}
        try:
            ev = json.loads(artist.evidence or "{}")
            if isinstance(ev, dict):
                stored_evidence = ev
        except Exception:
            stored_evidence = {}

        def leader_prove() -> dict:
            # Same collector helpers as registration: re-fetch each claimed
            # profile, grep for the fresh token. Last.fm keeps the account
            # maturity floor so a fresh sybil account can't be the proof.
            lastfm_key = self.lastfm_key
            pool_keys = self._lastfm_pool_list()
            if pool_keys:
                lastfm_key = pool_keys
            op = ownership_proofs
            proofs = {"soundcloud": False, "lastfm": False, "bandcamp": False, "youtube": False}
            lastfm_scrobbles = 0
            if op.get("soundcloud"):
                bio = _soundcloud_bio(_normalize_soundcloud(op["soundcloud"]))
                proofs["soundcloud"] = _token_in_text(bio, ownership_token)
            if op.get("lastfm"):
                body, scrobbles = _lastfm_profile_and_scrobbles(op["lastfm"], lastfm_key)
                lastfm_scrobbles = int(scrobbles)
                proofs["lastfm"] = (
                    _token_in_text(body, ownership_token)
                    and lastfm_scrobbles >= LASTFM_SCROBBLE_FLOOR
                )
            if op.get("bandcamp"):
                about = _bandcamp_about(_normalize_bandcamp(op["bandcamp"]))
                proofs["bandcamp"] = _token_in_text(about, ownership_token)
            if op.get("youtube"):
                desc = _youtube_description(op["youtube"])
                proofs["youtube"] = _token_in_text(desc, ownership_token)
            channels = sum(1 for v in proofs.values() if v)
            return {
                "proofs": proofs,
                "channels": channels,
                "token_present": channels > 0,
                "profile_matches_stored": _profile_clusters_overlap(stored_evidence, op),
                "lastfm_scrobbles": lastfm_scrobbles,
                "name_overlap": _name_token_overlap(name, artist.name),
            }

        def validator_fn(leader_result) -> bool:
            """Deterministic soundness of the recovery proof (no API re-fetch):
              - well-formed dict with sane channel count equal to the flags
              - token present on ≥1 channel
              - proof profile matches the ORIGINAL evidence per-platform
                (profile_matches_stored is recomputed here — it depends only
                on tx args + chain state, so the leader isn't trusted for it)
              - name overlap matches the recomputed value
              - Last.fm maturity floor holds when a Last.fm proof is claimed

            The only leader-trusted field is token presence itself (a live
            profile re-fetch — the same 'verify determinism' trade-off the
            registration path makes).
            """
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                d = json.loads(leader_result.calldata) if isinstance(
                    leader_result.calldata, str
                ) else leader_result.calldata
                if not isinstance(d, dict):
                    return False
                proofs = d.get("proofs") or {}
                if not isinstance(proofs, dict):
                    return False
                channels = int(d.get("channels", 0) or 0)
                expected_channels = sum(1 for v in proofs.values() if v)
                if channels < 1 or channels > 4 or channels != expected_channels:
                    return False
                if not d.get("token_present"):
                    return False
                if bool(d.get("profile_matches_stored")) != _profile_clusters_overlap(
                    stored_evidence, ownership_proofs
                ):
                    return False
                overlap = float(d.get("name_overlap", 0) or 0)
                if abs(overlap - _name_token_overlap(name, artist.name)) > 1e-9:
                    return False
                if not (0.0 <= overlap <= 1.0):
                    return False
                if proofs.get("lastfm") and int(
                    d.get("lastfm_scrobbles", 0) or 0
                ) < LASTFM_SCROBBLE_FLOOR:
                    return False
                return True
            except Exception:
                return False

        proof = gl.vm.run_nondet_unsafe(leader_prove, validator_fn)
        try:
            pd = proof if isinstance(proof, dict) else (
                json.loads(proof.calldata) if isinstance(proof.calldata, str)
                else proof.calldata
            )
        except Exception:
            pd = None
        if not isinstance(pd, dict) or not pd.get("token_present") or not pd.get("profile_matches_stored"):
            return "Recovery rejected — ALVERIFY token not found on a profile bound to this identity"

        # ── Migrate: identity stays, wallet pointer rotates ───────────────
        now = self._now()
        self.artists[sender] = Artist(
            wallet=sender,
            did=artist.did,
            name=artist.name,
            verified_at=u256(now),
            score=artist.score,
            evidence=artist.evidence,
            require_two_source=bool(artist.require_two_source),
        )
        # Re-point identity indexes.
        canon = artist.name.strip().lower()
        self.verified_by_name[canon] = new_wallet
        if ownership_token:
            self.verified_by_token[ownership_token] = new_wallet
        # Revoke the old wallet (TreeMap can't be iterated or deleted —
        # membership marker + tombstone is the revocation signal; views
        # short-circuit on it).
        self.revoked_wallets[old.lower()] = True
        self.artists[Address(old)] = Artist(
            wallet=Address(old),
            did="",
            name="",
            verified_at=u256(0),
            score=u256(0),
            evidence="{}",
            require_two_source=False,
        )
        # Carry reputation stats; zero the old wallet's.
        self.identity_score[sender] = self.identity_score.get(Address(old), u256(0))
        self.identity_count[sender] = self.identity_count.get(Address(old), u256(0))
        self.identity_score[Address(old)] = u256(0)
        self.identity_count[Address(old)] = u256(0)
        # Re-point anchored releases so is_verified_human() keeps working.
        migrated = self.artist_releases.get(Address(old))
        if migrated:
            self.artist_releases[sender] = migrated
            for h in migrated:
                rel = self.releases.get(h)
                if rel is not None:
                    rel.artist = sender
                    self.releases[h] = rel
            # Drop the orphaned old-wallet list (best-effort: GenVM DynArray
            # assignment from a plain list may be rejected — the old wallet
            # is revoked either way, so the leftover is unreachable).
            try:
                self.artist_releases[Address(old)] = []
            except Exception:
                pass
        return f"Identity migrated: {artist.name} now verified under {new_wallet} (old wallet revoked)"

    @gl.public.write
    def register_artist(
        self,
        did: str,
        name: str,
        audio_hash: bytes,
        source_urls: dict,  # {"bandcamp": "handle", "soundcloud": ..., ...}
        wallet: str,
        verification_source_1: str = "",
        verification_handle_1: str = "",
        verification_source_2: str = "",
        verification_handle_2: str = "",
        require_two_source: bool = True,
        ownership_token: str = "",   # ALVERIFY token the artist pasted into their profiles
        ownership_proofs: dict = {}, # {"soundcloud": "handle", "lastfm": "user", "bandcamp": "subdomain", "youtube": "handle"} — which profiles carry the token
    ) -> str:
        """
        Verify a wallet as belonging to a real human artist.

        Collects structured evidence from free public APIs, computes a
        0-100 score, and writes the artist to state if the score reaches
        70. The artist may supply up to two claimed verification sources
        (DISCO parity) — each resolves and cross-checks against the artist
        name, awarding W_TWO_SOURCE_MATCH if both match, W_SINGLE_SOURCE
        for one.

        `require_two_source` (default True): strict mode — if fewer than two
        claimed sources independently match, the score is capped at 5 (below
        the 70 threshold), so registration is effectively rejected at
        consensus. Set False for a relaxed single-source onboarding path.

        Identity dedup (one artist = one wallet): BEFORE any evidence work,
        if this ownership token or canonical name is already validated under
        a DIFFERENT wallet, registration is rejected. Same wallet can always
        re-register (updates the record; no double validation of the same
        person from a second wallet).
        """
        # ── Identity dedup gate (cheap, runs before the consensus work) ────
        sender = self._sender()
        canon_name = name.strip().lower()
        if ownership_token:
            existing = (self.verified_by_token[ownership_token]
                        if ownership_token in self.verified_by_token else "")
            if existing and str(existing).lower() != str(sender).lower():
                hint = (" identity moved — call reverify() from your new wallet"
                        if self._is_revoked(existing) else "")
                return f"Already validated under {existing}{hint} (no double validation)"
        if canon_name:
            existing = (self.verified_by_name[canon_name]
                        if canon_name in self.verified_by_name else "")
            if existing and str(existing).lower() != str(sender).lower():
                hint = (" identity moved — call reverify() from your new wallet"
                        if self._is_revoked(existing) else "")
                return f"Artist '{name}' already validated under {existing}{hint} (no double validation)"

        def leader_collect() -> Evidence:
            # Read API credentials from contract storage once. Inside
            # run_nondet_unsafe, all validators see the same stored
            # values, so passing them to the helpers keeps the consensus
            # path consistent.
            acoustid_key = self.acoustid_key
            spotify_token = self.spotify_token
            # Spotify: try the pool first (rate-limit failover), then the
            # single client pair, then any stored long-lived token.
            if not spotify_token:
                for pair in self._spotify_pool_list():
                    spotify_token = _spotify_mint_token(pair[0], pair[1])
                    if spotify_token:
                        break
            if not spotify_token and self.spotify_client_id and self.spotify_client_secret:
                spotify_token = _spotify_mint_token(self.spotify_client_id,
                                                    self.spotify_client_secret)
            lastfm_key = self.lastfm_key
            # Last.fm rate-limit pool: pool wins when seeded (round-robin
            # failover on error 29/10); single key is the fallback.
            pool_keys = self._lastfm_pool_list()
            if pool_keys:
                lastfm_key = pool_keys
            etherscan_key = self.etherscan_key

            ev = Evidence.empty()

            # Tier 1
            if ENABLE_ACOUSTID:
                matched, mbid = _acoustid_lookup(audio_hash, acoustid_key)
                ev.acoustid_matched = matched
                ev.acoustid_recording_mbid = mbid
                isrcs = _musicbrainz_isrc(mbid)
                for code in isrcs:
                    ev.isrc_codes.append(code)

            if ENABLE_SPOTIFY:
                sp = _spotify_search(name, spotify_token)
                if sp:
                    ev.spotify_artist_id = sp.get("id", "")
                    ev.spotify_verified = bool(sp.get("verified", False))
                    ev.spotify_name_matched = bool(sp.get("_name_matched", False))
                    ev.spotify_followers = u256(int(sp.get("followers", {}).get("total", 0) or 0))
                    ev.spotify_popularity = u256(int(sp.get("popularity", 0) or 0))

            title_hint = source_urls.get("release_title", "")
            apple_id, track_present = _apple_music_search(name, title_hint)
            ev.apple_music_artist_id = apple_id
            ev.apple_music_track_present = track_present

            # Tier 2 (from URLs the artist provided). We normalize each
            # URL to a bare handle before passing to the helpers, since
            # most tier-2 collectors either tolerate both forms (good)
            # or break on URLs (bad).
            ev.bandcamp_handle, ev.bandcamp_real_name, ev.bandcamp_location = (
                _bandcamp_check(_normalize_bandcamp(source_urls.get("bandcamp", "")))
            )
            ev.soundcloud_handle, ev.soundcloud_followers, ev.soundcloud_verified = (
                _soundcloud_check(_normalize_soundcloud(source_urls.get("soundcloud", "")))
            )
            ig_exists, ig_display, ig_bio = _instagram_fetch(
                _normalize_instagram(source_urls.get("instagram", "")))
            ev.instagram_handle = ig_exists  # truthy handle iff page exists
            ev.lastfm_scrobble_count = _lastfm_scrobbles(
                name, source_urls.get("lastfm", ""), lastfm_key
            )

            # Tier 2.5 — two-source verification (claimed sources + cross-check)
            ev.verification_source_1 = verification_source_1
            ev.verification_handle_1 = verification_handle_1
            ev.verification_source_2 = verification_source_2
            ev.verification_handle_2 = verification_handle_2
            match_total = 0
            if verification_source_1 and verification_handle_1 and _verify_claimed_source(
                verification_source_1, verification_handle_1, name,
                spotify_token, lastfm_key,
            ):
                match_total += 1
            if verification_source_2 and verification_handle_2 and _verify_claimed_source(
                verification_source_2, verification_handle_2, name,
                spotify_token, lastfm_key,
            ):
                match_total += 1
            ev.verification_match_count = u256(match_total)

            # Tier 2.6 — ownership proofs. The artist pasted an ALVERIFY
            # token into profiles they control; the leader re-fetches each
            # claimed profile and greps for the exact token. Last.fm adds
            # an account-maturity floor (LIFETIME_SCROBBLE_FLOOR): a token
            # on a fresh sybil account doesn't count.
            if ownership_token and ownership_proofs:
                op = ownership_proofs  # local alias for closure readability
                if op.get("soundcloud"):
                    bio = _soundcloud_bio(_normalize_soundcloud(op["soundcloud"]))
                    ev.ownership_proof_soundcloud = _token_in_text(bio, ownership_token)
                if op.get("lastfm"):
                    body, scrobbles = _lastfm_profile_and_scrobbles(op["lastfm"], lastfm_key)
                    ev.ownership_lastfm_scrobbles = u256(scrobbles)
                    ev.ownership_proof_lastfm = (
                        _token_in_text(body, ownership_token)
                        and scrobbles >= LASTFM_SCROBBLE_FLOOR
                    )
                if op.get("bandcamp"):
                    about = _bandcamp_about(_normalize_bandcamp(op["bandcamp"]))
                    ev.ownership_proof_bandcamp = _token_in_text(about, ownership_token)
                if op.get("youtube"):
                    desc = _youtube_description(op["youtube"])
                    ev.ownership_proof_youtube = _token_in_text(desc, ownership_token)

            # Tier 5
            ev.wallet_age_days = _wallet_age_days(wallet, etherscan_key)
            ens_name, _ = _ens_data(wallet)
            ev.ens_name = ens_name
            ev.ens_matches_artist = _name_token_overlap(ens_name, name) >= 0.5
            ev.farcaster_fname = _farcaster_fname(wallet)

            # Tier 3 (LLM)
            sources_summary = _build_sources_summary(ev, source_urls)
            ev.press_narrative_score = _llm_qualitative_adjustment(name, sources_summary)
            # Tier 3b (LLM identity guard) — SAME_ENTITY/DIFFERENT_ENTITY
            ev.llm_identity_match = _llm_identity_match(name, sources_summary)

            return ev

        def validator_fn(leader_result) -> bool:
            """Validator checks that the leader's evidence is SOUND (well-formed,
            internally plausible, not obviously fabricated).

            IMPORTANT: this does NOT decide whether the artist is verified.
            The threshold check (below this function, on the consensus_evidence
            score) is what gates verified/not-verified. The validator's job is
            narrower: confirm the evidence is structured and plausible enough
            that the score we compute from it is meaningful.

            Previous design: every validator independently re-ran all live
            API calls (leader_collect) and compared re-derived scores. On
            studionet the validators hit those same public APIs and drifted
            (rate limits, timing) -> UNDETERMINED.

            New design (deterministic): validators do NOT re-fetch any API.
            They parse the leader's evidence JSON, run plausibility guards,
            recompute the score deterministically, and require at least one
            tier-1 signal so an empty/phantom submission can't reach the
            threshold check. This is the "verify determinism, don't replay
            the world" pattern.

            Reject iff:
              1. leader_result is not a valid Return with calldata JSON.
              2. The evidence dict doesn't parse or has the wrong shape.
              3. Any numeric field is out of its plausible range.
              4. spotify_verified is set with zero followers (fabrication).
              5. bandcamp is in source_urls but bandcamp_handle is empty.
              6. The recomputed score is outside [0, 100].
              7. No tier-1 signal is present (AcoustID match, Spotify artist
                 id, Apple Music artist id, or any claimed source that
                 resolved AND name-bound to the claimed artist).
            """
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                leader_dict = json.loads(leader_result.calldata) if isinstance(
                    leader_result.calldata, str
                ) else leader_result.calldata
                if not isinstance(leader_dict, dict):
                    return False

                # Plausibility guards on the leader's evidence. These reject
                # fabricated or malformed submissions without needing to
                # re-fetch any API.
                followers = int(leader_dict.get("spotify_followers", 0) or 0)
                popularity = int(leader_dict.get("spotify_popularity", 0) or 0)
                if followers < 0 or popularity < 0 or popularity > 100:
                    return False
                if int(leader_dict.get("lastfm_scrobble_count", 0) or 0) < 0:
                    return False
                press = int(leader_dict.get("press_narrative_score", 0) or 0)
                if press < -5 or press > 5:
                    return False
                # A verified flag without a resolved artist id is impossible
                # (verified is only set when the artist lookup returns).
                if leader_dict.get("spotify_verified") and not leader_dict.get("spotify_artist_id"):
                    return False
                # bandcamp_handle must not be empty if claimed in source_urls.
                if source_urls.get("bandcamp") and not leader_dict.get("bandcamp_handle"):
                    return False
                # Ownership-proof fabrication guard: a claimed Last.fm proof
                # with a scrobble count below the maturity floor is a lie the
                # leader could have fabricated (mature accounts can't be
                # created in a block). Reject the whole evidence.
                if leader_dict.get("ownership_proof_lastfm") and int(
                    leader_dict.get("ownership_lastfm_scrobbles", 0) or 0
                ) < LASTFM_SCROBBLE_FLOOR:
                    return False

                leader_score = _score_evidence_from_dict(leader_dict, name)
                if leader_score < 0 or leader_score > 100:
                    return False

                # Soft floor: at least one REAL-WORLD presence signal must be
                # present. v0.6.1 (audit F2): verification_match_count no
                # longer counts — claimed sources are submitter-chosen, so
                # they can't be the floor. The floor's job is to block phantom
                # evidence with zero real-world presence.
                # v0.7.2: a confirmed ownership proof (ALVERIFY token on the
                # artist's own profile) also satisfies the floor — it is
                # stronger real-world evidence than a scraped catalog ID
                # (the token is physically on a profile the artist controls).
                has_tier1 = (
                    bool(leader_dict.get("acoustid_matched"))
                    or bool(leader_dict.get("spotify_artist_id"))
                    or bool(leader_dict.get("apple_music_artist_id"))
                    or bool(leader_dict.get("ownership_proof_soundcloud"))
                    or bool(leader_dict.get("ownership_proof_lastfm"))
                    or bool(leader_dict.get("ownership_proof_bandcamp"))
                    or bool(leader_dict.get("ownership_proof_youtube"))
                )
                return has_tier1
            except Exception:
                return False

        consensus_evidence = gl.vm.run_nondet_unsafe(leader_collect, validator_fn)
        score = _score_evidence(consensus_evidence, name)

        # Layer 3 — strict two-source mode. When the artist opts in
        # (require_two_source=True, the default), registration without two
        # independently matching claimed sources is capped far below the
        # verification threshold, so consensus rejects it.
        if require_two_source and int(_ev_get(consensus_evidence, "verification_match_count", 0)) < 2:
            score = min(score, 5)

        sender = self._sender()
        now = self._now()

        # Update running stats
        prev_count = int(self.identity_count.get(sender, u256(0)))
        self.identity_count[sender] = u256(prev_count + 1)
        self.identity_score[sender] = u256(score)

        if score >= int(VERIFICATION_THRESHOLD):
            self.artists[sender] = Artist(
                wallet=sender,
                did=did,
                name=name,
                verified_at=u256(now),
                score=u256(score),
                evidence=(
                    consensus_evidence.to_json()
                    if hasattr(consensus_evidence, "to_json")
                    else json.dumps(consensus_evidence)
                ),
                require_two_source=require_two_source,
            )
            # Index the identity so future wallets can't double-validate.
            if ownership_token:
                self.verified_by_token[ownership_token] = str(sender)
            if canon_name:
                self.verified_by_name[canon_name] = str(sender)
            return f"Verified ({score})"

        return f"Not verified ({score})"

    # ─── Release anchoring ────────────────────────────────────────────────

    @gl.public.write
    def anchor_release(
        self,
        audio_hash: bytes,
        title: str,
        contributors: DynArray[Address],
        release_date: u256,
    ) -> str:
        sender = self._sender()
        if sender not in self.artists:
            return "Not a verified artist"
        artist = self.artists[sender]
        # v0.7.1: a REVOKED wallet (reverify tombstone) must not keep write
        # power — it could anchor under the dead identity and squat audio
        # hashes, permanently blocking the real artist from anchoring them.
        if self._is_revoked(sender) or int(artist.score) < int(VERIFICATION_THRESHOLD):
            return "Not a verified artist"
        if self.releases.get(audio_hash) is not None:
            return "Audio hash already anchored"
        now = self._now()
        self.releases[audio_hash] = Release(
            artist=sender,
            title=title,
            audio_hash=audio_hash,
            contributors=contributors,
            release_date=release_date,
            anchored_at=u256(now),
            contested=False,
        )

        existing = self.artist_releases.get(sender, DynArray[bytes]())
        existing.append(audio_hash)
        self.artist_releases[sender] = existing

        return f"Anchored '{title}' for {artist.name}"

    # ─── Dispute filing ───────────────────────────────────────────────────

    @gl.public.write
    def dispute(
        self, audio_hash: bytes, claim: str, evidence_url: str
    ) -> str:
        release = self.releases.get(audio_hash)
        if release is None:
            return "Release not found"
        sender = self._sender()
        if release.artist == sender:
            return "Cannot dispute your own release"

        artist = self.artists[release.artist]

        def leader_judge() -> int:
            try:
                resp = gl.nondet.web.get(evidence_url)
                evidence_body = resp.body.decode("utf-8", errors="replace")
            except Exception:
                evidence_body = ""
            return _llm_judge_dispute(release, artist, claim, evidence_body)

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                own_score = leader_judge()
            except Exception:
                return False
            return abs(own_score - int(leader_result.calldata)) <= int(VALIDATOR_TOLERANCE)

        dispute_score = gl.vm.run_nondet_unsafe(leader_judge, validator_fn)

        self.disputes[audio_hash] = Dispute(
            audio_hash=audio_hash,
            claimant=sender,
            claim=claim,
            evidence_url=evidence_url,
            filed_at=u256(self._now()),
            resolution="Upheld" if dispute_score >= int(DISPUTE_UPHOLD_THRESHOLD) else "Dismissed",
        )

        if dispute_score >= int(DISPUTE_UPHOLD_THRESHOLD):
            release.contested = True
            self.releases[audio_hash] = release

            current_score = int(self.identity_score.get(release.artist, u256(70)))
            new_score = max(0, current_score - int(REPUTATION_PENALTY_PER_UPHELD_DISPUTE))
            self.identity_score[release.artist] = u256(new_score)
            if release.artist in self.artists:
                a = self.artists[release.artist]
                a.score = u256(new_score)
                if a.score < VERIFICATION_THRESHOLD:
                    a.verified_at = u256(0)
                self.artists[release.artist] = a

            return f"Dispute upheld (score {dispute_score}); release contested"
        return f"Dispute dismissed (score {dispute_score})"

    # ─── Read-only views ──────────────────────────────────────────────────

    @gl.public.view
    def is_verified_human(self, audio_hash: bytes) -> bool:
        release = self.releases.get(audio_hash)
        if release is None:
            return False
        if release.contested:
            return False
        artist = self.artists.get(release.artist)
        if artist is None:
            return False
        return artist.score >= VERIFICATION_THRESHOLD and artist.verified_at > u256(0)

    @gl.public.view
    def get_artist(self, wallet: Address) -> dict:
        if self._is_revoked(wallet):
            # Revoked wallet: identity moved elsewhere (reverify). Short-circuit
            # before the tombstone record so revoked reads are unambiguous.
            return {"verified": False, "revoked": True}
        artist = self.artists.get(wallet)
        if artist is None:
            return {"verified": False, "revoked": False}
        return {
            "verified": artist.score >= VERIFICATION_THRESHOLD
            and artist.verified_at > u256(0),
            "revoked": False,
            "did": artist.did,
            "name": artist.name,
            "score": int(artist.score),
            "verified_at": int(artist.verified_at),
        }

    @gl.public.view
    def get_release(self, audio_hash: bytes) -> dict:
        release = self.releases.get(audio_hash)
        if release is None:
            return {"found": False}
        contributors_list = []
        for c in release.contributors:
            contributors_list.append(str(c))
        return {
            "found": True,
            "title": release.title,
            "artist": str(release.artist),
            "contributors": contributors_list,
            "release_date": int(release.release_date),
            "anchored_at": int(release.anchored_at),
            "contested": release.contested,
        }

    @gl.public.view
    def get_dispute(self, audio_hash: bytes) -> dict:
        dispute = self.disputes.get(audio_hash)
        if dispute is None:
            return {"found": False}
        return {
            "found": True,
            "claimant": str(dispute.claimant),
            "claim": dispute.claim,
            "evidence_url": dispute.evidence_url,
            "filed_at": int(dispute.filed_at),
            "resolution": dispute.resolution,
        }


# ─── Helpers (used by validators) ─────────────────────────────────────────

def _name_tokens(s: str) -> set:
    """Lowercase alphanumeric token split — punctuation-insensitive, so
    'fred again..' == {'fred','again'} and 'M.I.A.' == {'mia'}."""
    import re
    return set(t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t)


def _name_token_overlap(a: str, b: str) -> float:
    """Jaccard similarity of two names.

    v0.6.1: tokenization now splits on non-alphanumerics instead of
    whitespace only — 'M.I.A.', 'burial', 'Aphex-Twin' tokenize sanely.
    Also: if either name is a single compound token that CONTAINS the
    other's full normalized form (e.g. username 'aphextwinofficial' vs
    'Aphex Twin' -> 'aphextwin'), that counts as containment overlap.
    Artists' usernames frequently concatenate or abbreviate the artist
    name; strict token equality would false-reject them.
    """
    import re
    if not a or not b:
        return 0.0
    a_tokens = _name_tokens(a)
    b_tokens = _name_tokens(b)
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    jaccard = len(intersection) / len(union)
    if jaccard >= 0.5:
        return jaccard
    # Compound-username containment: 'aphextwinofficial' vs {'aphex','twin'}
    a_join = re.sub(r"[^a-z0-9]", "", (a or "").lower())
    b_join = re.sub(r"[^a-z0-9]", "", (b or "").lower())
    if a_join and b_join:
        shorter, longer = (a_join, b_join) if len(a_join) <= len(b_join) else (b_join, a_join)
        # the claimed/artist name must appear IN FULL inside the other string
        if len(shorter) >= 4 and shorter in longer:
            return 0.5
    return jaccard


def _build_sources_summary(ev: Evidence, source_urls: dict) -> str:
    """Build a short text summary of the evidence for the LLM judge."""
    lines = []
    if ev.acoustid_matched:
        lines.append(f"AcoustID matched: recording {ev.acoustid_recording_mbid}")
    if len(ev.isrc_codes) > 0:
        lines.append(f"ISRC codes found: {list(ev.isrc_codes)}")
    if ev.spotify_artist_id:
        lines.append(
            f"Spotify: id={ev.spotify_artist_id}, verified={ev.spotify_verified}, "
            f"followers={int(ev.spotify_followers)}, popularity={int(ev.spotify_popularity)}"
        )
    if ev.apple_music_artist_id:
        lines.append(f"Apple Music: artist_id={ev.apple_music_artist_id}")
    if ev.bandcamp_handle:
        lines.append(
            f"Bandcamp: handle={ev.bandcamp_handle}, real_name={ev.bandcamp_real_name}, "
            f"location={ev.bandcamp_location}"
        )
    if ev.soundcloud_handle:
        lines.append(
            f"SoundCloud: handle={ev.soundcloud_handle}, followers={int(ev.soundcloud_followers)}, "
            f"verified={ev.soundcloud_verified}"
        )
    if ev.instagram_handle:
        lines.append(f"Instagram: handle={ev.instagram_handle}")
    if int(ev.lastfm_scrobble_count) > 0:
        lines.append(f"Last.fm scrobbles: {int(ev.lastfm_scrobble_count)}")
    ownership_flags = [
        name for name, key in (
            ("SoundCloud bio", "ownership_proof_soundcloud"),
            ("Last.fm profile", "ownership_proof_lastfm"),
            ("Bandcamp about", "ownership_proof_bandcamp"),
            ("YouTube description", "ownership_proof_youtube"),
        ) if getattr(ev, key, False)
    ]
    if ownership_flags:
        lines.append(f"Ownership proof tokens found in: {', '.join(ownership_flags)}")
    if ev.verification_source_1:
        lines.append(
            f"Source 1: {ev.verification_source_1}={ev.verification_handle_1} "
            f"(matched: {ev.verification_match_count}/2)"
        )
    if ev.ens_name:
        lines.append(f"ENS: {ev.ens_name} (matches: {ev.ens_matches_artist})")
    if ev.farcaster_fname:
        lines.append(f"Farcaster: {ev.farcaster_fname}")
    return "\n".join(lines) if lines else "No sources found."


def _score_evidence_from_dict(d: dict, name: str) -> int:
    """Reconstruct an Evidence from a dict and score it. Used by validators
    that receive the leader's Evidence as calldata."""
    try:
        # plain list — DynArray can't be user-instantiated
        isrc_codes = [code for code in d.get("isrc_codes", [])]
        ev = Evidence(
            acoustid_matched=bool(d.get("acoustid_matched", False)),
            acoustid_recording_mbid=d.get("acoustid_recording_mbid", ""),
            isrc_codes=isrc_codes,
            spotify_artist_id=d.get("spotify_artist_id", ""),
            spotify_verified=bool(d.get("spotify_verified", False)),
            spotify_name_matched=bool(d.get("spotify_name_matched", False)),
            spotify_followers=u256(int(d.get("spotify_followers", 0))),
            spotify_popularity=u256(int(d.get("spotify_popularity", 0))),
            apple_music_artist_id=d.get("apple_music_artist_id", ""),
            apple_music_track_present=bool(d.get("apple_music_track_present", False)),
            bandcamp_handle=d.get("bandcamp_handle", ""),
            bandcamp_real_name=d.get("bandcamp_real_name", ""),
            bandcamp_location=d.get("bandcamp_location", ""),
            soundcloud_handle=d.get("soundcloud_handle", ""),
            soundcloud_followers=u256(int(d.get("soundcloud_followers", 0))),
            soundcloud_verified=bool(d.get("soundcloud_verified", False)),
            instagram_handle=d.get("instagram_handle", ""),
            lastfm_scrobble_count=u256(int(d.get("lastfm_scrobble_count", 0))),
            ownership_proof_soundcloud=bool(d.get("ownership_proof_soundcloud", False)),
            ownership_proof_lastfm=bool(d.get("ownership_proof_lastfm", False)),
            ownership_proof_bandcamp=bool(d.get("ownership_proof_bandcamp", False)),
            ownership_proof_youtube=bool(d.get("ownership_proof_youtube", False)),
            ownership_lastfm_scrobbles=u256(int(d.get("ownership_lastfm_scrobbles", 0))),
            verification_source_1=d.get("verification_source_1", ""),
            verification_handle_1=d.get("verification_handle_1", ""),
            verification_source_2=d.get("verification_source_2", ""),
            verification_handle_2=d.get("verification_handle_2", ""),
            verification_match_count=u256(int(d.get("verification_match_count", 0))),
            wallet_age_days=u256(int(d.get("wallet_age_days", 0))),
            ens_name=d.get("ens_name", ""),
            ens_matches_artist=bool(d.get("ens_matches_artist", False)),
            farcaster_fname=d.get("farcaster_fname", ""),
            press_narrative_score=int(d.get("press_narrative_score", 0)),
            llm_identity_match=bool(d.get("llm_identity_match", True)),
        )
        return _score_evidence(ev, name)
    except Exception:
        return 0


def _llm_judge_dispute(release, artist, claim: str, evidence_body: str) -> int:
    """LLM judge for dispute merit. 0-100. Leader AND validators both call."""
    prompt = (
        f"You are adjudicating a provenance dispute on a music release.\n\n"
        f"Release:\n"
        f"  Title: {release.title}\n"
        f"  Audio hash: 0x{release.audio_hash.hex()}\n"
        f"  Anchored at: {release.anchored_at}\n"
        f"  Claimed release date: {release.release_date}\n\n"
        f"Claimed artist:\n"
        f"  Wallet: {artist.wallet}\n"
        f"  Name: {artist.name}\n"
        f"  DID: {artist.did}\n"
        f"  Verified at: {artist.verified_at} with score {artist.score}\n\n"
        f"Claim: {claim}\n"
        f"Evidence body:\n{evidence_body}\n\n"
        f"Score from 0 (no merit, dismiss) to 100 (clearly meritorious, "
        f"uphold). Use the source data; do not invent.\n\n"
        f"Respond with ONLY a single integer between 0 and 100."
    )
    raw = gl.nondet.exec_prompt(prompt)
    try:
        return int(raw.strip().split()[0])
    except Exception:
        return 0
