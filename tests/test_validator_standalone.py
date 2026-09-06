"""
test_validator_standalone.py — exercises the validator's pure logic
without requiring a genlayer runtime.

The new validator_fn in register_artist (commit 8be39ad) does three things
that are testable here:
  1. plausibility_guards(leader_dict) -> bool
  2. _score_evidence_from_dict(leader_dict, name) -> int
  3. has_tier1_signal(leader_dict) -> bool

This test file:
  - extracts those three checks into testable functions (mirroring the
    contract code) so future regressions can be caught without a deploy
  - verifies the rejection conditions listed in the validator docstring
  - verifies Burial's find_artist.py output would pass the validator
    and score above the verification threshold

NOT tested here (requires genlayer runtime):
  - the leader_collect() function itself
  - run_nondet_unsafe plumbing
  - the final threshold check (gated by `>= 70` on consensus_evidence score)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the contracts/ package importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── Mirror of the contract's validator logic ─────────────────────────────
# These functions reproduce the checks in ProvenanceRegistry.validator_fn
# (8be39ad). Keep them in sync with the contract.

W_ACOUSTID = 20
W_ISRC = 10
W_SPOTIFY = 10
W_APPLE_MUSIC = 5
W_BANDCAMP = 3
W_SOUNDCLOUD = 3
W_INSTAGRAM = 2
W_LASTFM = 2
W_TWO_SOURCE_MATCH = 15
W_SINGLE_SOURCE_MATCH = 8
W_WALLET_AGE = 5
W_WALLET_NAME = 5
W_LLM_ADJUSTMENT_RANGE = 5

VERIFICATION_THRESHOLD = 70


def plausibility_guards(leader_dict: dict, source_urls: dict | None = None) -> bool:
    """Returns True iff the leader's evidence passes all plausibility checks.

    Mirrors the guard block in ProvenanceRegistry.validator_fn (8be39ad).
    """
    followers = int(leader_dict.get("spotify_followers", 0) or 0)
    popularity = int(leader_dict.get("spotify_popularity", 0) or 0)
    if followers < 0 or popularity < 0 or popularity > 100:
        return False
    if int(leader_dict.get("lastfm_scrobble_count", 0) or 0) < 0:
        return False
    press = int(leader_dict.get("press_narrative_score", 0) or 0)
    if press < -5 or press > 5:
        return False
    if leader_dict.get("spotify_verified") and followers <= 0:
        return False
    src = source_urls or {}
    if src.get("bandcamp") and not leader_dict.get("bandcamp_handle"):
        return False
    return True


def has_tier1_signal(leader_dict: dict) -> bool:
    """Returns True iff at least one tier-1 signal is present.

    Mirrors the tier-1 floor added in 8be39ad.
    """
    return (
        bool(leader_dict.get("acoustid_matched"))
        or bool(leader_dict.get("spotify_artist_id"))
        or bool(leader_dict.get("apple_music_artist_id"))
        or int(leader_dict.get("verification_match_count", 0) or 0) > 0
    )


def score_evidence_from_dict(d: dict, name: str) -> int:
    """Mirrors _score_evidence in ProvenanceRegistry (line 614 of
    contracts/ProvenanceRegistry.py). Returns 0 on parse error.

    Pure-Python reproduction so the test can run without a genlayer
    runtime. Keep in sync with the contract — if the contract's
    scoring changes, update this function and re-run the suite.
    """
    try:
        score = 0
        # Tier 1 (max 45)
        if d.get("acoustid_matched"):
            score += W_ACOUSTID
        if d.get("isrc_codes"):
            score += W_ISRC
        sp = d.get("spotify_artist_id", "")
        if sp and (
            d.get("spotify_verified")
            or (int(d.get("spotify_popularity", 0) or 0) >= 20
                and int(d.get("spotify_followers", 0) or 0) >= 1000)
        ):
            score += W_SPOTIFY
        # Apple Music: W_APPLE_MUSIC is awarded ONCE if track_present.
        # apple_music_artist_id alone is not enough.
        if d.get("apple_music_track_present"):
            score += W_APPLE_MUSIC
        # Tier 2 (max 20)
        if d.get("bandcamp_handle"):
            score += W_BANDCAMP
        if d.get("soundcloud_handle") and (
            d.get("soundcloud_verified")
            or int(d.get("soundcloud_followers", 0) or 0) >= 100
        ):
            score += W_SOUNDCLOUD
        if d.get("instagram_handle"):
            score += W_INSTAGRAM
        if int(d.get("lastfm_scrobble_count", 0) or 0) >= 100:
            score += W_LASTFM
        # Tier 2.5
        mc = int(d.get("verification_match_count", 0) or 0)
        if mc >= 2:
            score += W_TWO_SOURCE_MATCH
        elif mc == 1:
            score += W_SINGLE_SOURCE_MATCH
        # Tier 5 (max 10)
        if int(d.get("wallet_age_days", 0) or 0) >= 90:
            score += W_WALLET_AGE
        if d.get("ens_matches_artist") or d.get("farcaster_fname"):
            score += W_WALLET_NAME
        # Tier 3 (LLM, ±5)
        press = int(d.get("press_narrative_score", 0) or 0)
        score += max(-W_LLM_ADJUSTMENT_RANGE, min(W_LLM_ADJUSTMENT_RANGE, press))
        return max(0, min(100, score))
    except Exception:
        return 0


def validator_accepts(leader_dict: dict, name: str, source_urls: dict | None = None) -> bool:
    """Returns True iff the new validator_fn (8be39ad) would accept this evidence.

    Mirrors the full control flow in the contract's validator_fn:
      - pass plausibility guards
      - score in [0, 100]
      - has tier-1 signal
    """
    if not plausibility_guards(leader_dict, source_urls):
        return False
    s = score_evidence_from_dict(leader_dict, name)
    if not (0 <= s <= 100):
        return False
    if not has_tier1_signal(leader_dict):
        return False
    return True


# ─── Fixtures ────────────────────────────────────────────────────────────

def empty_evidence() -> dict:
    return {
        "acoustid_matched": False,
        "acoustid_recording_mbid": "",
        "isrc_codes": [],
        "spotify_artist_id": "",
        "spotify_verified": False,
        "spotify_followers": 0,
        "spotify_popularity": 0,
        "apple_music_artist_id": "",
        "apple_music_track_present": False,
        "bandcamp_handle": "",
        "soundcloud_handle": "",
        "soundcloud_followers": 0,
        "soundcloud_verified": False,
        "instagram_handle": "",
        "lastfm_scrobble_count": 0,
        "verification_source_1": "",
        "verification_handle_1": "",
        "verification_source_2": "",
        "verification_handle_2": "",
        "verification_match_count": 0,
        "wallet_age_days": 0,
        "ens_name": "",
        "ens_matches_artist": False,
        "farcaster_fname": "",
        "press_narrative_score": 0,
    }


def burial_evidence() -> dict:
    """What Burial's find_artist.py output would produce if the leader
    successfully ran the full evidence collection. Sparse — only Apple Music
    + 2-source match. Real Burial would have more tier-1 signals in
    production (Spotify, AcoustID via MB cross-ref, etc.) but find_artist's
    free public endpoints don't reach them all.
    """
    ev = empty_evidence()
    ev["apple_music_artist_id"] = "468355684"
    ev["apple_music_track_present"] = True
    ev["verification_source_1"] = "apple_music"
    ev["verification_handle_1"] = "468355684"
    ev["verification_source_2"] = "musicbrainz"
    ev["verification_handle_2"] = "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"
    ev["verification_match_count"] = 2
    return ev


def burial_full_evidence() -> dict:
    """Burial with the full signal stack the leader would have on a real
    production registration: AcoustID match (via MB cross-ref to a real
    Burial recording), Spotify presence, Apple Music, Bandcamp, SoundCloud,
    Instagram, wallet age, ENS."""
    ev = burial_evidence()
    ev["acoustid_matched"] = True
    ev["acoustid_recording_mbid"] = "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6"
    ev["isrc_codes"] = ["GBBHS0700123"]
    ev["spotify_artist_id"] = "5LJ9AoZ4l9V3OQ0jVnF2Qa"
    ev["spotify_verified"] = False
    ev["spotify_followers"] = 850000
    ev["spotify_popularity"] = 78
    ev["bandcamp_handle"] = "burial"
    ev["soundcloud_handle"] = "burial"
    ev["soundcloud_followers"] = 50000
    ev["soundcloud_verified"] = True
    ev["instagram_handle"] = "burial"
    ev["lastfm_scrobble_count"] = 5000000
    ev["wallet_age_days"] = 1200
    ev["ens_name"] = "burial.eth"
    ev["ens_matches_artist"] = True
    ev["press_narrative_score"] = 3
    return ev


# ─── Tests ───────────────────────────────────────────────────────────────

def test_empty_evidence_rejected_by_tier1_floor():
    """Empty evidence: plausibility passes (no negatives), score is 0 (in range),
    but tier-1 floor rejects it."""
    ev = empty_evidence()
    assert score_evidence_from_dict(ev, "Anyone") == 0
    assert has_tier1_signal(ev) is False
    assert validator_accepts(ev, "Anyone") is False


def test_spotify_verified_with_zero_followers_rejected():
    """Fabrication red flag: spotify_verified=True but followers=0."""
    ev = empty_evidence()
    ev["spotify_artist_id"] = "fake"
    ev["spotify_verified"] = True
    ev["spotify_followers"] = 0
    assert plausibility_guards(ev) is False
    assert validator_accepts(ev, "Anyone") is False


def test_popularity_over_100_rejected():
    ev = empty_evidence()
    ev["spotify_artist_id"] = "x"
    ev["spotify_popularity"] = 150
    assert plausibility_guards(ev) is False


def test_negative_followers_rejected():
    ev = empty_evidence()
    ev["spotify_artist_id"] = "x"
    ev["spotify_followers"] = -1
    assert plausibility_guards(ev) is False


def test_press_score_out_of_range_rejected():
    ev = empty_evidence()
    ev["press_narrative_score"] = 10
    assert plausibility_guards(ev) is False
    ev2 = empty_evidence()
    ev2["press_narrative_score"] = -10
    assert plausibility_guards(ev2) is False


def test_bandcamp_in_source_urls_requires_handle():
    ev = empty_evidence()
    ev["spotify_artist_id"] = "x"  # so we'd otherwise have tier-1
    src = {"bandcamp": "https://bandcamp.com/somebody"}
    assert plausibility_guards(ev, src) is False
    ev["bandcamp_handle"] = "somebody"
    assert plausibility_guards(ev, src) is True


def test_burial_sparse_evidence_passes_validator_but_below_threshold():
    """Sparse Burial (only Apple Music + 2-source match) passes the new
    validator's soundness checks (no rejection) but scores below 70 — so
    the threshold check downstream correctly rejects verification."""
    ev = burial_evidence()
    s = score_evidence_from_dict(ev, "Burial")
    # Soundness: validator accepts (evidence is plausible, tier-1 present)
    assert validator_accepts(ev, "Burial") is True
    # But the score is below the verification threshold — this is the
    # expected outcome for a thin evidence submission.
    assert s < VERIFICATION_THRESHOLD, (
        f"Sparse Burial scored {s}, expected < {VERIFICATION_THRESHOLD}. "
        f"If this is now >= 70, the scoring changed — update this test."
    )


def test_burial_full_evidence_passes_threshold():
    """A real production Burial registration — full evidence — should
    clear the 70-point verification threshold."""
    ev = burial_full_evidence()
    s = score_evidence_from_dict(ev, "Burial")
    assert s >= VERIFICATION_THRESHOLD, (
        f"Full-evidence Burial scored {s}, expected >= {VERIFICATION_THRESHOLD}."
    )
    assert validator_accepts(ev, "Burial") is True


def test_realistic_artist_with_all_signals_scores_high():
    """A well-evidenced artist: AcoustID + Spotify + Apple + 2-source match +
    Bandcamp + SoundCloud + Instagram + Last.fm + wallet age + ENS."""
    ev = empty_evidence()
    ev["acoustid_matched"] = True
    ev["acoustid_recording_mbid"] = "abc-123"
    ev["isrc_codes"] = ["USRC17607839"]
    ev["spotify_artist_id"] = "real_artist"
    ev["spotify_verified"] = True
    ev["spotify_followers"] = 50000
    ev["spotify_popularity"] = 75
    ev["apple_music_artist_id"] = "12345"
    ev["apple_music_track_present"] = True
    ev["bandcamp_handle"] = "realartist"
    ev["soundcloud_handle"] = "realartist"
    ev["soundcloud_followers"] = 5000
    ev["soundcloud_verified"] = True
    ev["instagram_handle"] = "realartist"
    ev["lastfm_scrobble_count"] = 500
    ev["verification_match_count"] = 2
    ev["wallet_age_days"] = 365
    ev["ens_name"] = "realartist.eth"
    ev["press_narrative_score"] = 2
    s = score_evidence_from_dict(ev, "Real Artist")
    assert s >= VERIFICATION_THRESHOLD
    assert validator_accepts(ev, "Real Artist") is True


def test_phantom_with_only_tier2_signals_rejected():
    """An artist with only tier-2 signals (bandcamp, soundcloud, etc.) but no
    tier-1 (no AcoustID, no Spotify, no Apple, no two-source) is rejected by
    the new tier-1 floor."""
    ev = empty_evidence()
    ev["bandcamp_handle"] = "ghost"
    ev["soundcloud_handle"] = "ghost"
    ev["instagram_handle"] = "ghost"
    assert has_tier1_signal(ev) is False
    assert validator_accepts(ev, "Ghost") is False


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--no-header"]))
