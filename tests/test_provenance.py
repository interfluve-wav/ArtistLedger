"""
Unit tests for OnChainProvenanceRegistry v0.2.0

These tests run against the GenLayer VM with mocked web calls and mocked
LLM responses. They verify:

  - Evidence collection across 13 structured fields
  - Deterministic scoring (Tier 1+2+5 + bounded LLM adjustment)
  - State transitions (verified/not verified, anchored/not anchored,
    contested/not contested)
  - The asymmetric dispute mechanism (60 uphold threshold vs 70 verification)
  - The reputation penalty flow when a dispute is upheld
  - Edge cases (re-anchoring same hash, dispute on own release, etc.)
  - The read-only view methods

Each test mocks the underlying API functions directly so the contract
logic is tested in isolation from network access.
"""

from unittest.mock import patch

import pytest

from contracts.ProvenanceRegistry import (
    Evidence,
    ProvenanceRegistry,
    VERIFICATION_THRESHOLD,
    DISPUTE_UPHOLD_THRESHOLD,
    REPUTATION_PENALTY_PER_UPHELD_DISPUTE,
    W_ACOUSTID, W_ISRC, W_SPOTIFY, W_APPLE_MUSIC,
    W_BANDCAMP, W_SOUNDCLOUD, W_INSTAGRAM, W_LASTFM,
    W_WALLET_AGE, W_WALLET_NAME, W_LLM_ADJUSTMENT_RANGE,
    _score_evidence,
    _name_token_overlap,
    u256,
    DynArray,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def contract():
    return ProvenanceRegistry()


@pytest.fixture
def artist_wallet():
    return "0xArtistWallet"


@pytest.fixture
def attacker_wallet():
    return "0xAttackerWallet"


@pytest.fixture
def audio_hash():
    return b"\x01" * 32


@pytest.fixture
def source_urls():
    return {
        "bandcamp": "skeemask",
        "soundcloud": "skeemask",
        "instagram": "skeemask",
        "lastfm": "skeemask",
        "release_title": "Compro",
    }


def make_evidence(
    acoustid=True, mbid="abc-123", isrcs=None,
    spotify_id="spotify123", spotify_verified=True,
    spotify_followers=5000, spotify_popularity=45,
    apple_id="apple123", apple_track=True,
    bandcamp="skeemask", bandcamp_real="Skee Mask", bandcamp_loc="Berlin",
    soundcloud="skeemask", soundcloud_followers=2000, soundcloud_verified=False,
    instagram="skeemask", lastfm_scrobbles=500,
    wallet_age=200, ens_name="skeemask.eth", ens_matches=True,
    farcaster="skeemask", press_score=3,
):
    isrc_dyn = DynArray[str]()
    for code in (isrcs or ["GBAHT1800123"]):
        isrc_dyn.append(code)
    return Evidence(
        acoustid_matched=acoustid,
        acoustid_recording_mbid=mbid,
        isrc_codes=isrc_dyn,
        spotify_artist_id=spotify_id,
        spotify_verified=spotify_verified,
        spotify_followers=u256(spotify_followers),
        spotify_popularity=u256(spotify_popularity),
        apple_music_artist_id=apple_id,
        apple_music_track_present=apple_track,
        bandcamp_handle=bandcamp,
        bandcamp_real_name=bandcamp_real,
        bandcamp_location=bandcamp_loc,
        soundcloud_handle=soundcloud,
        soundcloud_followers=u256(soundcloud_followers),
        soundcloud_verified=soundcloud_verified,
        instagram_handle=instagram,
        lastfm_scrobble_count=u256(lastfm_scrobbles),
        wallet_age_days=u256(wallet_age),
        ens_name=ens_name,
        ens_matches_artist=ens_matches,
        farcaster_fname=farcaster,
        press_narrative_score=press_score,
    )


def _make_artist(wallet, *, score=80):
    from contracts.ProvenanceRegistry import Artist
    return Artist(
        wallet=wallet,
        did="did:web:test",
        name="Skee Mask",
        verified_at=u256(1000),
        score=u256(score),
        evidence="{}",
    )


def _make_release(wallet, audio_hash, *, title="Test"):
    from contracts.ProvenanceRegistry import Release, DynArray
    return Release(
        artist=wallet,
        title=title,
        audio_hash=audio_hash,
        contributors=DynArray([wallet]),
        release_date=u256(1234567890),
        anchored_at=u256(2000),
        contested=False,
    )


# ─── Evidence empty() ──────────────────────────────────────────────────────


def test_evidence_empty_has_no_signals():
    ev = Evidence.empty()
    assert ev.acoustid_matched is False
    assert len(ev.isrc_codes) == 0
    assert ev.spotify_artist_id == ""
    assert ev.bandcamp_handle == ""
    assert ev.press_narrative_score == 0
    assert ev.wallet_age_days == u256(0)


# ─── _name_token_overlap ───────────────────────────────────────────────────


def test_name_token_overlap_identical():
    assert _name_token_overlap("Skee Mask", "Skee Mask") == 1.0


def test_name_token_overlap_partial():
    s = _name_token_overlap("skeemask.eth", "Skee Mask")
    assert 0.0 < s < 1.0


def test_name_token_overlap_disjoint():
    assert _name_token_overlap("Aphex Twin", "Burial") == 0.0


def test_name_token_overlap_empty():
    assert _name_token_overlap("", "Skee Mask") == 0.0
    assert _name_token_overlap("Skee Mask", "") == 0.0


# ─── _score_evidence ───────────────────────────────────────────────────────


def test_score_full_evidence_reaches_100_plus_llm_bonus():
    ev = make_evidence(press_score=5)
    score = _score_evidence(ev, "Skee Mask")
    assert score == 100


def test_score_min_evidence_is_zero():
    ev = Evidence.empty()
    assert _score_evidence(ev, "") == 0


def test_score_only_acoustid():
    ev = Evidence.empty()
    ev.acoustid_matched = True
    assert _score_evidence(ev, "X") == W_ACOUSTID


def test_score_only_spotify_verified():
    ev = Evidence.empty()
    ev.spotify_artist_id = "abc"
    ev.spotify_verified = True
    assert _score_evidence(ev, "X") == W_SPOTIFY


def test_score_spotify_unverified_but_popular():
    ev = Evidence.empty()
    ev.spotify_artist_id = "abc"
    ev.spotify_verified = False
    ev.spotify_followers = u256(2000)
    ev.spotify_popularity = u256(25)
    assert _score_evidence(ev, "X") == W_SPOTIFY


def test_score_spotify_unknown_fails_threshold():
    ev = Evidence.empty()
    ev.spotify_artist_id = "abc"
    ev.spotify_verified = False
    ev.spotify_followers = u256(50)
    ev.spotify_popularity = u256(5)
    assert _score_evidence(ev, "X") == 0


def test_score_isrc_full_credit():
    ev = Evidence.empty()
    isrcs = DynArray[str]()
    isrcs.append("GBAHT1800123")
    ev.isrc_codes = isrcs
    assert _score_evidence(ev, "X") == W_ISRC


def test_score_bandcamp_only():
    ev = Evidence.empty()
    ev.bandcamp_handle = "skeemask"
    assert _score_evidence(ev, "X") == W_BANDCAMP


def test_score_soundcloud_verified():
    ev = Evidence.empty()
    ev.soundcloud_handle = "skeemask"
    ev.soundcloud_verified = True
    assert _score_evidence(ev, "X") == W_SOUNDCLOUD


def test_score_soundcloud_unverified_but_popular():
    ev = Evidence.empty()
    ev.soundcloud_handle = "skeemask"
    ev.soundcloud_followers = u256(200)
    assert _score_evidence(ev, "X") == W_SOUNDCLOUD


def test_score_soundcloud_tiny_account_no_credit():
    ev = Evidence.empty()
    ev.soundcloud_handle = "skeemask"
    ev.soundcloud_followers = u256(50)
    ev.soundcloud_verified = False
    assert _score_evidence(ev, "X") == 0


def test_score_instagram_only():
    ev = Evidence.empty()
    ev.instagram_handle = "skeemask"
    assert _score_evidence(ev, "X") == W_INSTAGRAM


def test_score_lastfm_minimum_100_scrobbles():
    ev = Evidence.empty()
    ev.lastfm_scrobble_count = u256(100)
    assert _score_evidence(ev, "X") == W_LASTFM


def test_score_lastfm_below_threshold_no_credit():
    ev = Evidence.empty()
    ev.lastfm_scrobble_count = u256(99)
    assert _score_evidence(ev, "X") == 0


def test_score_wallet_age_90_days():
    ev = Evidence.empty()
    ev.wallet_age_days = u256(90)
    assert _score_evidence(ev, "X") == W_WALLET_AGE


def test_score_wallet_age_under_90_no_credit():
    ev = Evidence.empty()
    ev.wallet_age_days = u256(89)
    assert _score_evidence(ev, "X") == 0


def test_score_wallet_name_link_via_ens():
    ev = Evidence.empty()
    ev.ens_name = "skeemask.eth"
    ev.ens_matches_artist = True
    assert _score_evidence(ev, "X") == W_WALLET_NAME


def test_score_wallet_name_link_via_farcaster():
    ev = Evidence.empty()
    ev.farcaster_fname = "skeemask"
    assert _score_evidence(ev, "X") == W_WALLET_NAME


def test_score_llm_adjustment_clamped_positive():
    ev = Evidence.empty()
    ev.press_narrative_score = 100
    assert _score_evidence(ev, "X") == W_LLM_ADJUSTMENT_RANGE


def test_score_llm_adjustment_clamped_negative():
    ev = Evidence.empty()
    ev.press_narrative_score = -100
    assert _score_evidence(ev, "X") == 0


def test_score_70_threshold_achievable_with_minimal_real_artist():
    ev = make_evidence(
        acoustid=True,
        isrcs=["GBAHT1800123"],
        spotify_verified=True,
        apple_track=True,
        bandcamp="skeemask",
        soundcloud="skeemask", soundcloud_verified=True,
        instagram="skeemask",
        lastfm_scrobbles=100,
        wallet_age=200,
        ens_matches=True,
        press_score=0,
    )
    assert _score_evidence(ev, "Skee Mask") == 70


# ─── register_artist (integration with mocked APIs) ────────────────────────


def test_register_artist_verified_when_score_reaches_70(
    contract, artist_wallet, audio_hash, source_urls
):
    with patch("contracts.ProvenanceRegistry._acoustid_lookup", return_value=(True, "mbid-1")), \
         patch("contracts.ProvenanceRegistry._musicbrainz_isrc", return_value=DynArray(["ISRC123"])), \
         patch("contracts.ProvenanceRegistry._spotify_search", return_value={
             "id": "sp1", "verified": True, "followers": {"total": 5000}, "popularity": 45
         }), \
         patch("contracts.ProvenanceRegistry._apple_music_search", return_value=("ap1", True)), \
         patch("contracts.ProvenanceRegistry._bandcamp_check", return_value=("skeemask", "Skee Mask", "Berlin")), \
         patch("contracts.ProvenanceRegistry._soundcloud_check", return_value=("skeemask", 2000, True)), \
         patch("contracts.ProvenanceRegistry._instagram_check", return_value="skeemask"), \
         patch("contracts.ProvenanceRegistry._lastfm_scrobbles", return_value=500), \
         patch("contracts.ProvenanceRegistry._wallet_age_days", return_value=200), \
         patch("contracts.ProvenanceRegistry._ens_data", return_value=("skeemask.eth", True)), \
         patch("contracts.ProvenanceRegistry._farcaster_fname", return_value="skeemask"), \
         patch("contracts.ProvenanceRegistry._llm_qualitative_adjustment", return_value=3), \
         patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=1000):
        result = contract.register_artist(
            did="did:web:skee.mask",
            name="Skee Mask",
            audio_hash=audio_hash,
            source_urls=source_urls,
            wallet=artist_wallet,
        )
    assert "Verified" in result
    assert artist_wallet in contract.artists
    assert contract.artists[artist_wallet].score >= 70


def test_register_artist_not_verified_when_no_signals(
    contract, artist_wallet, audio_hash, source_urls
):
    with patch("contracts.ProvenanceRegistry._acoustid_lookup", return_value=(False, "")), \
         patch("contracts.ProvenanceRegistry._musicbrainz_isrc", return_value=DynArray()), \
         patch("contracts.ProvenanceRegistry._spotify_search", return_value={}), \
         patch("contracts.ProvenanceRegistry._apple_music_search", return_value=("", False)), \
         patch("contracts.ProvenanceRegistry._bandcamp_check", return_value=("", "", "")), \
         patch("contracts.ProvenanceRegistry._soundcloud_check", return_value=("", 0, False)), \
         patch("contracts.ProvenanceRegistry._instagram_check", return_value=""), \
         patch("contracts.ProvenanceRegistry._lastfm_scrobbles", return_value=0), \
         patch("contracts.ProvenanceRegistry._wallet_age_days", return_value=0), \
         patch("contracts.ProvenanceRegistry._ens_data", return_value=("", False)), \
         patch("contracts.ProvenanceRegistry._farcaster_fname", return_value=""), \
         patch("contracts.ProvenanceRegistry._llm_qualitative_adjustment", return_value=0), \
         patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=1000):
        result = contract.register_artist(
            did="did:web:fake",
            name="Fake Artist",
            audio_hash=audio_hash,
            source_urls=source_urls,
            wallet=artist_wallet,
        )
    assert "Not verified" in result
    assert artist_wallet not in contract.artists
    assert contract.identity_count[artist_wallet] == 1
    assert contract.identity_score[artist_wallet] == u256(0)


# ─── anchor_release ────────────────────────────────────────────────────────


def test_anchor_release_succeeds_for_verified_artist(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x02" * 32
    with patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=2000):
        result = contract.anchor_release(
            audio_hash=audio_hash,
            title="Test EP",
            contributors=DynArray([artist_wallet]),
            release_date=1234567890,
        )
    assert "Anchored" in result
    assert contract.releases[audio_hash].title == "Test EP"


def test_anchor_release_rejects_unverified_wallet(contract, attacker_wallet):
    audio_hash = b"\x03" * 32
    with patch.object(contract, "_sender", return_value=attacker_wallet):
        result = contract.anchor_release(
            audio_hash=audio_hash,
            title="Fake",
            contributors=DynArray([attacker_wallet]),
            release_date=1234567890,
        )
    assert result == "Not a verified artist"


def test_anchor_release_rejects_duplicate_hash(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x04" * 32
    with patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=2000):
        contract.anchor_release(audio_hash, "First", DynArray([artist_wallet]), 1000)
        result = contract.anchor_release(audio_hash, "Second", DynArray([artist_wallet]), 2000)
    assert "already anchored" in result


# ─── dispute ───────────────────────────────────────────────────────────────


def test_dispute_upheld_marks_contested_and_penalizes(
    contract, artist_wallet, attacker_wallet
):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x05" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch("contracts.ProvenanceRegistry._llm_judge_dispute", return_value=80), \
         patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=5000):
        # Override sender for the dispute call itself
        contract._sender = lambda: attacker_wallet
        result = contract.dispute(
            audio_hash=audio_hash,
            claim="This is Suno-generated",
            evidence_url="https://example.com/ai-evidence",
        )
    assert "upheld" in result
    assert contract.releases[audio_hash].contested is True
    assert contract.identity_score[artist_wallet] == 80 - REPUTATION_PENALTY_PER_UPHELD_DISPUTE
    assert contract.artists[artist_wallet].verified_at == u256(0)


def test_dispute_dismissed_leaves_release_clean(
    contract, artist_wallet, attacker_wallet
):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x06" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch("contracts.ProvenanceRegistry._llm_judge_dispute", return_value=20), \
         patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=5000):
        contract._sender = lambda: attacker_wallet
        result = contract.dispute(
            audio_hash=audio_hash,
            claim="No evidence really",
            evidence_url="https://example.com/nothing",
        )
    assert "dismissed" in result
    assert contract.releases[audio_hash].contested is False
    assert contract.identity_score[artist_wallet] == u256(80)


def test_dispute_on_own_release_rejected(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x07" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch.object(contract, "_sender", return_value=artist_wallet):
        result = contract.dispute(audio_hash, "self-dispute", "https://x.com")
    assert "Cannot dispute your own release" in result


def test_dispute_on_unknown_release_rejected(contract, attacker_wallet):
    with patch.object(contract, "_sender", return_value=attacker_wallet):
        result = contract.dispute(b"\x08" * 32, "claim", "https://x.com")
    assert "Release not found" in result


# ─── is_verified_human ─────────────────────────────────────────────────────


def test_is_verified_human_true_for_clean_release(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x09" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)
    assert contract.is_verified_human(audio_hash) is True


def test_is_verified_human_false_for_unknown_hash(contract):
    assert contract.is_verified_human(b"\x0a" * 32) is False


def test_is_verified_human_false_for_contested(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x0b" * 32
    release = _make_release(artist_wallet, audio_hash)
    release.contested = True
    contract.releases[audio_hash] = release
    assert contract.is_verified_human(audio_hash) is False


def test_is_verified_human_false_for_low_score(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=60)
    audio_hash = b"\x0c" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)
    assert contract.is_verified_human(audio_hash) is False


# ─── View methods ──────────────────────────────────────────────────────────


def test_get_artist_unregistered(contract, artist_wallet):
    assert contract.get_artist(artist_wallet) == {"verified": False}


def test_get_artist_verified(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=85)
    result = contract.get_artist(artist_wallet)
    assert result["verified"] is True
    assert result["name"] == "Skee Mask"
    assert result["score"] == 85


def test_get_release(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x0d" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash, title="Compro")
    result = contract.get_release(audio_hash)
    assert result["found"] is True
    assert result["title"] == "Compro"
    assert result["contested"] is False


def test_get_release_unknown(contract):
    assert contract.get_release(b"\x0e" * 32) == {"found": False}


def test_get_dispute(contract, artist_wallet, attacker_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x0f" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch("contracts.ProvenanceRegistry._llm_judge_dispute", return_value=80), \
         patch.object(contract, "_sender", return_value=artist_wallet), \
         patch.object(contract, "_now", return_value=5000):
        contract._sender = lambda: attacker_wallet
        contract.dispute(audio_hash, "claim", "https://x.com")
        result = contract.get_dispute(audio_hash)
    assert result["found"] is True
    assert result["resolution"] == "Upheld"


# ─── Constants / thresholds ───────────────────────────────────────────────


def test_verification_threshold_is_70():
    assert VERIFICATION_THRESHOLD == u256(70)


def test_dispute_threshold_is_lower_than_verification():
    assert DISPUTE_UPHOLD_THRESHOLD < VERIFICATION_THRESHOLD


def test_reputation_penalty_is_10():
    assert REPUTATION_PENALTY_PER_UPHELD_DISPUTE == u256(10)
