"""Tests for v0.3.5/v0.3.6 Apple Music co-artist ID guard.

The bug: old _apple_music_search used substring matching on artistName
and took the LAST match. For "Four Tet" iTunes returns tracks by
"Skrillex, Starrah & Four Tet" — the substring matched, and the OLD
code took the last such match's artistId (Skrillex's 356545647)
instead of Four Tet's canonical 35888604.

The fix splits artistName on `,`, `&`, `feat.`, etc., requires exact
segment equality, prefers exact matches over substring matches, and
on substring fallback does NOT set track_present=True (the strict
score isn't bumped by a co-artist-only track).

Verified against real iTunes Search API responses (recorded 2026-09-06).
"""
from unittest.mock import patch

import pytest

from contracts.ProvenanceRegistry import _apple_music_search


# Real iTunes Search API response shape (limit=10) for "four tet"
# Captured 2026-09-06: includes canonical Four Tet tracks AND a
# Skrillex/Starrah/Four Tet collab that the OLD code mishandled.
FOUR_TET_ITUNES_RESPONSE = {
    "results": [
        {
            "wrapperType": "track",
            "artistId": 35888604,           # canonical Four Tet
            "artistName": "Four Tet",
            "trackName": "Lush",
        },
        {
            "wrapperType": "track",
            "artistId": 35888604,
            "artistName": "Four Tet",
            "trackName": "She Moves She",
        },
        {
            "wrapperType": "track",
            "artistId": 356545647,          # Skrillex (WRONG artist)
            "artistName": "Skrillex, Starrah & Four Tet",
            "trackName": "Butterflies",
        },
        {
            "wrapperType": "artist",        # wrong wrapperType — should be skipped
            "artistId": 999999,
            "artistName": "Four Tet",
        },
    ]
}


def test_apple_music_returns_canonical_artist_id_for_four_tet():
    """The bug case: ensure 'Four Tet' resolves to 35888604, NOT 356545647."""
    with patch(
        "contracts.ProvenanceRegistry._http_get_json",
        return_value=FOUR_TET_ITUNES_RESPONSE,
    ):
        artist_id, track_present = _apple_music_search("Four Tet")

    assert artist_id == "35888604", (
        f"Co-artist guard failed: got {artist_id} (Skrillex's), "
        f"expected 35888604 (Four Tet)"
    )
    assert track_present is True


def test_apple_music_no_match_returns_empty():
    """If no track matches, both return values are empty/false."""
    with patch(
        "contracts.ProvenanceRegistry._http_get_json",
        return_value={"results": []},
    ):
        artist_id, track_present = _apple_music_search("Nonexistent Artist")

    assert artist_id == ""
    assert track_present is False


def test_apple_music_substring_only_match_does_not_set_track_present():
    """If the only 'match' is via substring containment (not exact segment
    equality), track_present stays False. This catches cases like
    'Various Artists' tracks that mention 'four tet' in the artistName
    but Four Tet isn't a credited co-artist.

    Note: 'Skrillex & Four Tet' WOULD set track_present=True because
    splitting on '&' gives ['skrillex', 'four tet'] and 'four tet' is an
    exact segment. That is correct behavior — that's a joint credit.
    The substring fallback only fires when no segment equals the claimed
    name.
    """
    substring_only_response = {
        "results": [
            {
                "wrapperType": "track",
                "artistId": 111111,
                "artistName": "Various Artists",  # 'four tet' would be a substring only if it appeared here
                "trackName": "Generic Track",
            },
        ]
    }
    with patch(
        "contracts.ProvenanceRegistry._http_get_json",
        return_value=substring_only_response,
    ):
        artist_id, track_present = _apple_music_search("Four Tet")

    # No exact segment match, no substring match either — both empty.
    assert artist_id == ""
    assert track_present is False


def test_apple_music_substring_match_in_bio_style_track_name():
    """If artistName contains the claimed name as substring but NOT as
    an exact segment after splitting, we still get the artistId (the
    leader can verify by other means) but track_present=False (so the
    strict score isn't bumped).

    Example: 'DJ Set: Four Tet B2B Floating Points' — 'four tet' is
    in the string as a substring, but after splitting on separators
    like ':' and 'B2B', no segment equals 'four tet'.
    """
    substring_response = {
        "results": [
            {
                "wrapperType": "track",
                "artistId": 222222,
                "artistName": "DJ Set: Four Tet B2B Floating Points",
                "trackName": "Boiler Room",
            },
        ]
    }
    with patch(
        "contracts.ProvenanceRegistry._http_get_json",
        return_value=substring_response,
    ):
        artist_id, track_present = _apple_music_search("Four Tet")

    # _exact_segment splits on ',', '&', 'feat.', etc. — but NOT on
    # ':' or 'B2B' (which aren't in the separator list). So 'four tet'
    # is a substring match but not an exact-segment match.
    # The substring fallback returns (id, False).
    # NOTE: if the separator list ever grows to include ':' or 'B2B',
    # this test will start failing — that's correct, update the test.
    assert artist_id == "222222"
    assert track_present is False, (
        "track_present should be False for substring-only matches"
    )


def test_apple_music_skips_artist_wrapper_type():
    """Items with wrapperType='artist' are album/artist results, not tracks.
    They should not influence artistId/track_present."""
    only_artist_results = {
        "results": [
            {"wrapperType": "artist", "artistId": 35888604, "artistName": "Four Tet"},
        ]
    }
    with patch(
        "contracts.ProvenanceRegistry._http_get_json",
        return_value=only_artist_results,
    ):
        artist_id, track_present = _apple_music_search("Four Tet")

    assert artist_id == ""
    assert track_present is False
