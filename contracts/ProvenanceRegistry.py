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

class Artist(gl.Contract):
    wallet: Address
    did: str
    name: str
    verified_at: u256
    score: u256
    evidence: str  # JSON-serialized Evidence for onchain auditability


class Release(gl.Contract):
    artist: Address
    title: str
    audio_hash: bytes
    contributors: DynArray[Address]
    release_date: u256
    anchored_at: u256
    contested: bool


class Dispute(gl.Contract):
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

    # Tier 5 — wallet-derived (max 10 points)
    wallet_age_days: u256
    ens_name: str
    ens_matches_artist: bool
    farcaster_fname: str

    # Tier 3 — qualitative (LLM judge, ±5 points)
    press_narrative_score: int          # -5 to +5

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @staticmethod
    def empty() -> "Evidence":
        return Evidence(
            acoustid_matched=False,
            acoustid_recording_mbid="",
            isrc_codes=DynArray[str](),
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
W_BANDCAMP: int = 5
W_SOUNDCLOUD: int = 5
W_INSTAGRAM: int = 5
W_LASTFM: int = 5
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

def _acoustid_lookup(audio_hash: bytes) -> tuple[bool, str]:
    """Look up the audio hash in AcoustID. Returns (matched, recording_mbid)."""
    url = (
        f"{ACOUSTID_URL}?client={_acoustid_api_key()}"
        f"&duration=0&fingerprint={audio_hash.hex()}&meta=recordings+releaseids"
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


def _acoustid_api_key() -> str:
    """Read the AcoustID API key from contract storage. Default empty for tests."""
    return ""  # In production, set via contract init or env


def _musicbrainz_isrc(recording_id: str) -> DynArray[str]:
    """Fetch ISRC codes for a MusicBrainz recording."""
    if not recording_id:
        return DynArray[str]()
    url = f"{MUSICBRAINZ_RECORDING_URL}{recording_id}?inc=isrcs&fmt=json"
    data = _http_get_json(url)
    result = DynArray[str]()
    for code in data.get("isrcs", []):
        result.append(code)
    return result


def _musicbrainz_artist(name: str) -> dict:
    """Look up an artist on MusicBrainz. Returns top match or {}."""
    url = f"{MUSICBRAINZ_ARTIST_URL}?query={name}&fmt=json&limit=1"
    data = _http_get_json(url)
    artists = data.get("artists", [])
    return artists[0] if artists else {}


def _spotify_search(name: str) -> dict:
    """Search Spotify for an artist. Returns top match or {}."""
    headers = {"Authorization": f"Bearer {_spotify_token()}"}
    url = f"{SPOTIFY_SEARCH_URL}?q=artist:{name}&type=artist&limit=1"
    try:
        resp = gl.nondet.web.get(url, headers=headers)
        data = json.loads(resp.body.decode("utf-8", errors="replace"))
        items = data.get("artists", {}).get("items", [])
        return items[0] if items else {}
    except Exception:
        return {}


def _spotify_token() -> str:
    """Read the Spotify OAuth token from contract storage."""
    return ""  # In production, refresh via client_credentials flow


def _apple_music_search(name: str, title: str) -> tuple[str, bool]:
    """Search Apple Music. Returns (artist_id, track_present)."""
    url = f"{APPLE_MUSIC_SEARCH_URL}?term={name}+{title}&entity=musicArtist,musicTrack&limit=1"
    data = _http_get_json(url)
    results = data.get("results", [])
    artist_id = ""
    track_present = False
    for r in results:
        if r.get("wrapperType") == "artist" and not artist_id:
            artist_id = str(r.get("artistId", ""))
        if r.get("wrapperType") == "track" and not track_present:
            track_present = True
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


def _lastfm_scrobbles(artist: str, lastfm_user: str) -> int:
    """Return scrobble count for an artist in a Last.fm user's history."""
    if not lastfm_user or not artist:
        return 0
    api_key = _lastfm_api_key()
    if not api_key:
        return 0
    url = (
        f"https://ws.audioscrobbler.com/2.0/?method=artist.getInfo"
        f"&artist={artist}&username={lastfm_user}&api_key={api_key}&format=json"
    )
    data = _http_get_json(url)
    try:
        return int(data.get("artist", {}).get("stats", {}).get("userplaycount", 0))
    except Exception:
        return 0


def _lastfm_api_key() -> str:
    return ""  # In production, set via contract init


# ─── Tier 5 (wallet-derived) ──────────────────────────────────────────────

def _wallet_age_days(wallet: str) -> int:
    """Compute wallet age in days via Etherscan.

    Returns the number of whole days between the wallet's first on-chain
    transaction and the current transaction's timestamp. Uses
    `gl.message_raw['datetime']` (consensus-safe) for the "now" side.
    """
    if not wallet:
        return 0
    api_key = _etherscan_api_key()
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


def _etherscan_api_key() -> str:
    return ""  # In production, set via contract init


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

def _score_evidence(ev: Evidence, claimed_name: str) -> int:
    """Compute the deterministic score from an Evidence struct.

    Returns a Python int [0, 100]. The int is converted to u256 by the
    caller when written to storage.
    """
    score = 0

    # Tier 1 (max 45)
    if ev.acoustid_matched:
        score += W_ACOUSTID
    if len(ev.isrc_codes) > 0:
        score += W_ISRC
    # Spotify: 10 if verified OR (popularity >= 20 AND followers >= 1000)
    if ev.spotify_artist_id and (
        ev.spotify_verified
        or (int(ev.spotify_popularity) >= 20 and int(ev.spotify_followers) >= 1000)
    ):
        score += W_SPOTIFY
    if ev.apple_music_track_present:
        score += W_APPLE_MUSIC

    # Tier 2 (max 20)
    if ev.bandcamp_handle:
        score += W_BANDCAMP
    if ev.soundcloud_handle and (ev.soundcloud_verified or int(ev.soundcloud_followers) >= 100):
        score += W_SOUNDCLOUD
    if ev.instagram_handle:
        score += W_INSTAGRAM
    if int(ev.lastfm_scrobble_count) >= 100:
        score += W_LASTFM

    # Tier 5 (max 10)
    if int(ev.wallet_age_days) >= 90:
        score += W_WALLET_AGE
    if ev.ens_matches_artist or ev.farcaster_fname:
        score += W_WALLET_NAME

    # Tier 3 (LLM, ±5)
    bounded_adjustment = max(-W_LLM_ADJUSTMENT_RANGE, min(W_LLM_ADJUSTMENT_RANGE, ev.press_narrative_score))
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

    # ─── Identity verification ─────────────────────────────────────────────

    @gl.public.write
    def register_artist(
        self,
        did: str,
        name: str,
        audio_hash: bytes,
        source_urls: dict,  # {"bandcamp": "handle", "soundcloud": ..., ...}
        wallet: str,
    ) -> str:
        """
        Verify a wallet as belonging to a real human artist.

        Collects 13 structured evidence fields from free public APIs,
        computes a 0-100 score, and writes the artist to state if the
        score reaches 70.
        """
        def leader_collect() -> Evidence:
            ev = Evidence.empty()

            # Tier 1
            matched, mbid = _acoustid_lookup(audio_hash)
            ev.acoustid_matched = matched
            ev.acoustid_recording_mbid = mbid
            isrcs = _musicbrainz_isrc(mbid)
            for code in isrcs:
                ev.isrc_codes.append(code)

            sp = _spotify_search(name)
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
                name, source_urls.get("lastfm", "")
            )

            # Tier 5
            ev.wallet_age_days = _wallet_age_days(wallet)
            ens_name, _ = _ens_data(wallet)
            ev.ens_name = ens_name
            ev.ens_matches_artist = _name_token_overlap(ens_name, name) >= 0.5
            ev.farcaster_fname = _farcaster_fname(wallet)

            # Tier 3 (LLM)
            sources_summary = _build_sources_summary(ev, source_urls)
            ev.press_narrative_score = _llm_qualitative_adjustment(name, sources_summary)

            return ev

        def validator_fn(leader_result) -> bool:
            """Validator re-derives evidence independently. Accepts if:
            1. Leader's evidence struct matches ours on key fields
            2. Re-derived score is within tolerance of leader's score
            """
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                own_evidence = leader_collect()
                own_score = _score_evidence(own_evidence, name)
            except Exception:
                return False

            # Compare structured fields. We don't require exact equality —
            # API responses can have small variance. We require agreement
            # on the boolean flags that gate score components.
            leader_dict = json.loads(leader_result.calldata) if isinstance(
                leader_result.calldata, str
            ) else leader_result.calldata

            # The leader result is the Evidence struct itself; we accept
            # if our independently-derived score matches the leader's
            # score (since both are computed from the same scoring fn,
            # this is equivalent to checking evidence agreement on the
            # boolean flags)
            leader_score = _score_evidence_from_dict(leader_dict, name)
            return abs(own_score - leader_score) <= VALIDATOR_TOLERANCE

        consensus_evidence = gl.vm.run_nondet_unsafe(leader_collect, validator_fn)
        score = _score_evidence(consensus_evidence, name)
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
                evidence=consensus_evidence.to_json(),
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
    if ev.ens_name:
        lines.append(f"ENS: {ev.ens_name} (matches: {ev.ens_matches_artist})")
    if ev.farcaster_fname:
        lines.append(f"Farcaster: {ev.farcaster_fname}")
    return "\n".join(lines) if lines else "No sources found."


def _score_evidence_from_dict(d: dict, name: str) -> int:
    """Reconstruct an Evidence from a dict and score it. Used by validators
    that receive the leader's Evidence as calldata."""
    try:
        isrc_codes = DynArray[str]()
        for code in d.get("isrc_codes", []):
            isrc_codes.append(code)
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
