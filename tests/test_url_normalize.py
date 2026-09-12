"""Tests for v0.3.6 tier-2 URL normalization helpers.

These were added because the frontend sends full URLs (e.g.
"https://mindex.bandcamp.com/") but the contract helpers expect bare
handles. Without normalization, the helper builds
"https://https://mindex.bandcamp.com/.bandcamp.com" which 404s and
silently breaks tier-2 verification.
"""
import pytest
from contracts.ProvenanceRegistry import (
    _normalize_bandcamp,
    _normalize_soundcloud,
    _normalize_instagram,
)


@pytest.mark.parametrize("raw,expected", [
    # The main bug-fix case: frontend sends full URL
    ("https://mindex.bandcamp.com/", "mindex"),
    ("https://mindex.bandcamp.com", "mindex"),
    ("http://mindex.bandcamp.com/", "mindex"),
    # Bare handle passes through unchanged
    ("mindex", "mindex"),
    # Edge cases
    ("", ""),
    ("fourtet", "fourtet"),
    # https:// prefix with a path should still extract the subdomain
    ("https://boards-of-canada.bandcamp.com/album/music-has-the-right-to-children",
     "boards-of-canada"),
])
def test_normalize_bandcamp_extracts_bare_handle(raw, expected):
    assert _normalize_bandcamp(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("https://soundcloud.com/four-tet", "four-tet"),
    ("https://soundcloud.com/skrillex/", "skrillex"),
    ("https://soundcloud.com/caribou?ref=twitter", "caribou"),
    ("@four-tet", "four-tet"),  # bare @-prefixed handle
    ("four-tet", "four-tet"),
    ("", ""),
])
def test_normalize_soundcloud_extracts_bare_handle(raw, expected):
    assert _normalize_soundcloud(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("https://www.instagram.com/fourtet/", "fourtet"),
    ("https://instagram.com/skrillex", "skrillex"),
    ("@fourtet", "fourtet"),
    ("fourtet", "fourtet"),
    ("", ""),
])
def test_normalize_instagram_extracts_bare_handle(raw, expected):
    assert _normalize_instagram(raw) == expected
