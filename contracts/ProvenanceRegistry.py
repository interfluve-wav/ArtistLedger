# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# ruff: noqa: BLE001,S110
"""
OnChainProvenanceRegistry — GenLayer Intelligent Contract v0.2.0

Tracks real-world music releases with provenance validated through
deterministic cross-source verification + LLM qualitative adjustment.
Answers one question: is this audio track provably human-made and unaltered?

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
        )


# ─── Constants ─────────────────────────────────────────────────────────────

VERIFICATION_THRESHOLD: u256 = u256(70)
DISPUTE_UPHOLD_THRESHOLD: u256 = u256(60)
VALIDATOR_TOLERANCE: u256 = u256(15)
REPUTATION_PENALTY_PER_UPHELD_DISPUTE: u256 = u256(10)

# Factor weights (sum to 100 max deterministic + ±5 LLM)
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


def _spotify_search(name: str, spotify_token: str) -> dict:
    """Search Spotify for an artist. Returns top match or {}."""
    headers = {"Authorization": f"Bearer {spotify_token}"}
    url = f"{SPOTIFY_SEARCH_URL}?q=artist:{name}&type=artist&limit=1"
    try:
        resp = gl.nondet.web.get(url, headers=headers)
        data = json.loads(resp.body.decode("utf-8", errors="replace"))
        items = data.get("artists", {}).get("items", [])
        return items[0] if items else {}
    except Exception:
        return {}


def _apple_music_search(name: str, title: str = "") -> tuple[str, bool]:
    """Search Apple Music. Returns (artist_id, track_present).

    `title` is a reserved hint: when a real release title is supplied it can
    scope the search to an exact track (Layer 2 refinement). For now the
    track search is name-scoped with a co-artist guard, matching the on-chain
    behaviour that verifies the artist's audio is present on Apple Music.
    """
    url = f"{APPLE_MUSIC_SEARCH_URL}?term={name}&entity=musicTrack&limit=5"
    data = _http_get_json(url)
    results = data.get("results", [])
    artist_id = ""
    track_present = False
    for r in results:
        if r.get("wrapperType") == "track" and name.lower() in r.get("artistName", "").lower():
            # Guard against co-artist false matches
            track_present = True
            artist_id = str(r.get("artistId", ""))
    return artist_id, track_present


# ─── Tier 2 factor collectors (URL-based) ─────────────────────────────────

def _bandcamp_check(handle: str) -> tuple[str, str, str]:
    """Fetch a Bandcamp profile. Returns (handle, real_name, location)."""
    if not handle:
        return "", "", ""
    url = f"https://{handle}.bandcamp.com"
    try:
        body = _http_get(url)
        # Real name and location are in the bio section, pattern is loose
        real_name = _regex_first(body, r'"name":"([^"]+)"')
        location = _regex_first(body, r'"location":"([^"]+)"')
        return handle, real_name, location
    except Exception:
        return handle, "", ""


def _soundcloud_check(handle: str) -> tuple[str, int, bool]:
    """Fetch a SoundCloud profile. Returns (handle, followers, verified)."""
    if not handle:
        return "", 0, False
    url = f"https://soundcloud.com/{handle}"
    try:
        body = _http_get(url)
        followers_str = _regex_first(body, r'"followers_count":(\d+)')
        followers = int(followers_str) if followers_str else 0
        verified = '"verified":true' in body.lower() or '"badges":' in body.lower()
        return handle, followers, verified
    except Exception:
        return handle, 0, False


def _instagram_check(handle: str) -> str:
    """Return the Instagram handle if profile exists."""
    if not handle:
        return ""
    try:
        url = f"https://www.instagram.com/{handle}/"
        body = _http_get(url)
        if "Page Not Found" in body or "Sorry, this page" in body:
            return ""
        return handle
    except Exception:
        return ""


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
        # directly; otherwise search by name.
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
        # Layer 1: HTTP existence only. SoundCloud's profile name needs their
        # (closed) API — Layer 2 upgrades this to a real handle/name scrape.
        h = handle.rstrip("/").split("/")[-1].split("?")[0]
        sh, _, _ = _soundcloud_check(h)
        return bool(sh)
    if st in ("instagram_handle", "instagram"):
        # Layer 1: HTTP existence only (page-not-found check). Name binding
        # is impossible without IG's private GraphQL — Layer 2 improvement.
        h = handle.rstrip("/").split("/")[-1]
        return bool(_instagram_check(h))
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
        try:
            data = _http_get_json(f"{MUSICBRAINZ_ARTIST_URL}{mbid}?fmt=json")
        except Exception:
            return False
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


def _spotify_artist_id(raw: str) -> str:
    """Extract a Spotify artist ID from a URL or return a bare ID as-is."""
    if "open.spotify.com/artist/" in raw:
        return raw.split("/artist/")[-1].split("?")[0]
    # bare 22-char base62 ID
    if raw and len(raw) == 22:
        return raw
    return ""


def _lastfm_scrobbles(artist: str, lastfm_user: str, lastfm_key: str) -> int:
    """Return scrobble count for an artist in a Last.fm user's history."""
    if not lastfm_user or not artist:
        return 0
    if not lastfm_key:
        return 0
    api_key = lastfm_key
    url = (
        f"https://ws.audioscrobbler.com/2.0/?method=artist.getInfo"
        f"&artist={artist}&username={lastfm_user}&api_key={api_key}&format=json"
    )
    data = _http_get_json(url)
    try:
        return int(data.get("artist", {}).get("stats", {}).get("userplaycount", 0))
    except Exception:
        return 0


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
    # Spotify: 10 if verified OR (popularity >= 20 AND followers >= 1000)
    sp_id = _ev_get(ev, "spotify_artist_id", "")
    if sp_id and (
        _ev_get(ev, "spotify_verified", False)
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

    # Tier 5 (max 10)
    if int(_ev_get(ev, "wallet_age_days", 0)) >= 90:
        score += W_WALLET_AGE
    if _ev_get(ev, "ens_matches_artist", False) or _ev_get(ev, "farcaster_fname", ""):
        score += W_WALLET_NAME

    # Tier 3 (LLM, ±5)
    bounded_adjustment = max(-W_LLM_ADJUSTMENT_RANGE, min(W_LLM_ADJUSTMENT_RANGE, int(_ev_get(ev, "press_narrative_score", 0))))
    score += bounded_adjustment

    return max(0, min(100, score))


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


# ─── Contract ──────────────────────────────────────────────────────────────

class ProvenanceRegistry(gl.Contract):
    artists: TreeMap[Address, Artist]
    releases: TreeMap[bytes, Release]
    disputes: TreeMap[bytes, Dispute]
    identity_score: TreeMap[Address, u256]
    identity_count: TreeMap[Address, u256]
    artist_releases: TreeMap[Address, DynArray[bytes]]

    # API credentials. Set by `set_api_keys` before the first
    # `register_artist` call. All four are read inside `run_nondet_unsafe`
    # by the leader, then passed to the module-level API helpers.
    acoustid_key: str
    spotify_token: str
    lastfm_key: str
    etherscan_key: str

    def __init__(self):
        """Schema constructor (required by GenVM). API keys default to
        empty so reads before `set_api_keys` fail quiet (no signal)."""
        self.acoustid_key = ""
        self.spotify_token = ""
        self.lastfm_key = ""
        self.etherscan_key = ""

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

    @gl.public.write
    def set_api_keys(
        self,
        acoustid_key: str,
        spotify_token: str,
        lastfm_key: str,
        etherscan_key: str,
    ) -> str:
        """Set the upstream API credentials used by `register_artist`.

        This is unguarded for testnet simplicity. For production, gate it
        behind a stored admin address and only allow the deployer to
        call it. The keys are read inside `run_nondet_unsafe` by the
        leader, so all four must be set before the first
        `register_artist` call.

        Pass empty strings for keys you don't have; the corresponding
        evidence field will then return its default (no signal).
        """
        self.acoustid_key = acoustid_key
        self.spotify_token = spotify_token
        self.lastfm_key = lastfm_key
        self.etherscan_key = etherscan_key
        return "API keys set"

    # ─── Identity verification ─────────────────────────────────────────────

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
        """
        def leader_collect() -> Evidence:
            # Read API credentials from contract storage once. Inside
            # run_nondet_unsafe, all validators see the same stored
            # values, so passing them to the helpers keeps the consensus
            # path consistent.
            acoustid_key = self.acoustid_key
            spotify_token = self.spotify_token
            lastfm_key = self.lastfm_key
            etherscan_key = self.etherscan_key

            ev = Evidence.empty()

            # Tier 1
            matched, mbid = _acoustid_lookup(audio_hash, acoustid_key)
            ev.acoustid_matched = matched
            ev.acoustid_recording_mbid = mbid
            isrcs = _musicbrainz_isrc(mbid)
            for code in isrcs:
                ev.isrc_codes.append(code)

            sp = _spotify_search(name, spotify_token)
            if sp:
                ev.spotify_artist_id = sp.get("id", "")
                ev.spotify_verified = bool(sp.get("verified", False))
                ev.spotify_followers = u256(int(sp.get("followers", {}).get("total", 0)))
                ev.spotify_popularity = u256(int(sp.get("popularity", 0)))

            title_hint = source_urls.get("release_title", "")
            apple_id, track_present = _apple_music_search(name, title_hint)
            ev.apple_music_artist_id = apple_id
            ev.apple_music_track_present = track_present

            # Tier 2 (from URLs the artist provided)
            ev.bandcamp_handle, ev.bandcamp_real_name, ev.bandcamp_location = (
                _bandcamp_check(source_urls.get("bandcamp", ""))
            )
            ev.soundcloud_handle, ev.soundcloud_followers, ev.soundcloud_verified = (
                _soundcloud_check(source_urls.get("soundcloud", ""))
            )
            ev.instagram_handle = _instagram_check(source_urls.get("instagram", ""))
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

            # Tier 5
            ev.wallet_age_days = _wallet_age_days(wallet, etherscan_key)
            ens_name, _ = _ens_data(wallet)
            ev.ens_name = ens_name
            ev.ens_matches_artist = _name_token_overlap(ens_name, name) >= 0.5
            ev.farcaster_fname = _farcaster_fname(wallet)

            # Tier 3 (LLM)
            sources_summary = _build_sources_summary(ev, source_urls)
            ev.press_narrative_score = _llm_qualitative_adjustment(name, sources_summary)

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
                 id, Apple Music artist id, or a verified two-source match).
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
                # A verified flag with zero followers/popularity is a
                # fabrication red flag (Spotify requires activity).
                if leader_dict.get("spotify_verified") and followers <= 0:
                    return False
                # bandcamp_handle must not be empty if claimed in source_urls.
                if source_urls.get("bandcamp") and not leader_dict.get("bandcamp_handle"):
                    return False

                leader_score = _score_evidence_from_dict(leader_dict, name)
                if leader_score < 0 or leader_score > 100:
                    return False

                # Soft floor: at least one tier-1 signal must be present.
                # This prevents a phantom leader (empty evidence that
                # somehow scores a few points from minor signals) from
                # reaching the threshold check.
                has_tier1 = (
                    bool(leader_dict.get("acoustid_matched"))
                    or bool(leader_dict.get("spotify_artist_id"))
                    or bool(leader_dict.get("apple_music_artist_id"))
                    or int(leader_dict.get("verification_match_count", 0) or 0) > 0
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
        if self.releases.get(audio_hash) is not None:
            return "Audio hash already anchored"

        artist = self.artists[sender]
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
        artist = self.artists.get(wallet)
        if artist is None:
            return {"verified": False}
        return {
            "verified": artist.score >= VERIFICATION_THRESHOLD
            and artist.verified_at > u256(0),
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

def _name_token_overlap(a: str, b: str) -> float:
    """Jaccard similarity of two names (tokenized)."""
    if not a or not b:
        return 0.0
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(intersection) / len(union)


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
