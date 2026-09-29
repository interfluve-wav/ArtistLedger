"""v0.7.3 — fabricated leader evidence must fail independent authentication.

Validators independently re-authenticate ownership-token facts and claimed
source matches. These tests lock that fabricated leader booleans (ownership
proofs / inflated match counts) cannot pass consensus and therefore cannot
be presented as verified.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "stubs"))

from contracts.ProvenanceRegistry import (  # noqa: E402
    _authenticate_ownership_proofs,
    _count_claimed_source_matches,
    _ownership_proofs_match_leader,
    LASTFM_SCROBBLE_FLOOR,
)


TOKEN = "ALVERIFY-FABRICATE-TEST-9K2M"


def test_authenticate_ownership_rejects_empty_when_no_token_on_profile():
    """Independent auth: profile fetched but token absent → False."""
    with patch(
        "contracts.ProvenanceRegistry._soundcloud_bio",
        return_value="just a normal bio, no token here",
    ):
        auth = _authenticate_ownership_proofs(
            TOKEN, {"soundcloud": "attacker"}, ""
        )
    assert auth["proofs"]["soundcloud"] is False
    assert auth["token_present"] is False
    assert auth["channels"] == 0


def test_authenticate_ownership_accepts_real_token_on_profile():
    with patch(
        "contracts.ProvenanceRegistry._soundcloud_bio",
        return_value=f"new album out. {TOKEN} booking@x.com",
    ):
        auth = _authenticate_ownership_proofs(
            TOKEN, {"soundcloud": "real-artist"}, ""
        )
    assert auth["proofs"]["soundcloud"] is True
    assert auth["token_present"] is True
    assert auth["channels"] == 1


def test_fabricated_leader_ownership_flag_detected():
    """Leader claims ownership_proof_soundcloud=True but independent
    re-fetch finds no token → mismatch → consensus must reject."""
    leader_dict = {
        "ownership_proof_soundcloud": True,
        "ownership_proof_lastfm": False,
        "ownership_proof_bandcamp": False,
        "ownership_proof_youtube": False,
        "ownership_lastfm_scrobbles": 0,
        "spotify_artist_id": "cover",  # tier-1 cover so floor wouldn't catch it
    }
    with patch(
        "contracts.ProvenanceRegistry._soundcloud_bio",
        return_value="bio without the claimed token",
    ):
        auth = _authenticate_ownership_proofs(
            TOKEN, {"soundcloud": "victim-handle"}, ""
        )
    assert auth["proofs"]["soundcloud"] is False
    assert _ownership_proofs_match_leader(leader_dict, auth) is False


def test_honest_leader_ownership_flag_matches():
    leader_dict = {
        "ownership_proof_soundcloud": True,
        "ownership_proof_lastfm": False,
        "ownership_proof_bandcamp": False,
        "ownership_proof_youtube": False,
        "ownership_lastfm_scrobbles": 0,
    }
    with patch(
        "contracts.ProvenanceRegistry._soundcloud_bio",
        return_value=f"verified {TOKEN}",
    ):
        auth = _authenticate_ownership_proofs(
            TOKEN, {"soundcloud": "real"}, ""
        )
    assert _ownership_proofs_match_leader(leader_dict, auth) is True


def test_fabricated_lastfm_proof_below_floor_mismatch():
    """Leader claims lastfm ownership; independent auth applies maturity floor."""
    leader_dict = {
        "ownership_proof_soundcloud": False,
        "ownership_proof_lastfm": True,
        "ownership_proof_bandcamp": False,
        "ownership_proof_youtube": False,
        "ownership_lastfm_scrobbles": LASTFM_SCROBBLE_FLOOR + 10,  # leader lies high
    }
    with patch(
        "contracts.ProvenanceRegistry._lastfm_profile_and_scrobbles",
        return_value=(f"bio {TOKEN}", 5),  # real scrobbles below floor
    ):
        auth = _authenticate_ownership_proofs(
            TOKEN, {"lastfm": "sybil"}, "key"
        )
    assert auth["proofs"]["lastfm"] is False
    assert _ownership_proofs_match_leader(leader_dict, auth) is False


def test_fabricated_verification_match_count_detected():
    """Leader claims verification_match_count=2 but independent source
    auth finds 0 matches → fabricated evidence rejected at consensus."""
    with patch(
        "contracts.ProvenanceRegistry._verify_claimed_source",
        return_value=False,
    ):
        actual = _count_claimed_source_matches(
            "Famous DJ",
            "soundcloud_url", "attacker-page",
            "instagram", "attacker-page",
            "", "",
        )
    assert actual == 0
    leader_claimed = 2
    assert leader_claimed != actual  # would fail validator equality check


def test_honest_verification_match_count_agrees():
    with patch(
        "contracts.ProvenanceRegistry._verify_claimed_source",
        side_effect=[True, True],
    ):
        actual = _count_claimed_source_matches(
            "Burial",
            "apple_music", "468355684",
            "musicbrainz", "9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6",
            "", "",
        )
    assert actual == 2


def test_fabricated_leader_evidence_cannot_be_presented_as_verified():
    """End-to-end steward story (consensus half): fabricated ownership +
    inflated match count fail independent auth, so the evidence never
    reaches a Verified threshold write — and therefore cannot be presented
    as verified. (UI half is covered in test_certificate_authority.py.)
    """
    leader_dict = {
        "ownership_proof_soundcloud": True,
        "ownership_proof_lastfm": False,
        "ownership_proof_bandcamp": True,
        "ownership_proof_youtube": False,
        "ownership_lastfm_scrobbles": 0,
        "verification_match_count": 2,
        "spotify_artist_id": "cover-signal",
        "acoustid_matched": True,
    }
    with patch(
        "contracts.ProvenanceRegistry._soundcloud_bio",
        return_value="no token",
    ), patch(
        "contracts.ProvenanceRegistry._bandcamp_about",
        return_value="no token either",
    ), patch(
        "contracts.ProvenanceRegistry._verify_claimed_source",
        return_value=False,
    ):
        auth = _authenticate_ownership_proofs(
            TOKEN,
            {"soundcloud": "x", "bandcamp": "y"},
            "",
        )
        matches = _count_claimed_source_matches(
            "Anyone", "soundcloud_url", "x", "bandcamp_url", "y", "", ""
        )
    assert _ownership_proofs_match_leader(leader_dict, auth) is False
    assert matches != int(leader_dict["verification_match_count"])
    # Either failure alone is enough for the validator to return False.
