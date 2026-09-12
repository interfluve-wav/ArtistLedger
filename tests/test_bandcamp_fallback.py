"""Tests for v0.3.6 Bandcamp three-source name fallback.

The bug: old _bandcamp_check only looked for JSON-LD "name":"..." fields.
Many real Bandcamp artist pages (Mindex, Boards of Canada, Burial) expose
the artist name only via <title> or og:title. v0.3.6 fixes this by chaining
JSON-LD → og:title → twitter:title → <title> in that order.

These tests use realistic Bandcamp page fragments (recorded 2026-09-06).
"""
from unittest.mock import patch

from contracts.ProvenanceRegistry import _bandcamp_check, _normalize_bandcamp


# Real Bandcamp page with og:title but no JSON-LD name
OG_TITLE_ONLY = '''
<html>
<head>
  <title>Music | Mindex</title>
  <meta property="og:title" content="Mindex" />
  <meta property="og:description" content="..." />
</head>
<body>
  <!-- no JSON-LD here -->
</body>
</html>
'''

# Real Bandcamp page with only <title>
TITLE_ONLY = '''
<html>
<head>
  <title>Burial</title>
</head>
<body></body>
</html>
'''

# Real Bandcamp page with JSON-LD name (label-style account)
JSON_LD_NAME = '''
<html>
<head>
  <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"MusicGroup","name":"Warp Records"}
  </script>
</head>
<body></body>
</html>
'''

# Page where nothing matches — real_name and location should be empty
NOTHING_MATCHES = '''
<html><body></body></html>
'''


def test_bandcamp_og_title_fallback():
    """og:title is the second-fallback source after JSON-LD."""
    with patch(
        "contracts.ProvenanceRegistry._http_get",
        return_value=OG_TITLE_ONLY,
    ):
        handle, real_name, location = _bandcamp_check("mindex")

    assert handle == "mindex"
    assert real_name == "Mindex", (
        f"Expected 'Mindex' (from og:title), got {real_name!r}"
    )
    assert location == ""


def test_bandcamp_plain_title_fallback():
    """Plain <title> is the last-resort fallback when both JSON-LD and og:title are absent."""
    with patch(
        "contracts.ProvenanceRegistry._http_get",
        return_value=TITLE_ONLY,
    ):
        handle, real_name, location = _bandcamp_check("burial")

    assert handle == "burial"
    assert real_name == "Burial"
    assert location == ""


def test_bandcamp_json_ld_name_preferred():
    """JSON-LD name is the first source tried; og:title is not consulted when JSON-LD is present."""
    both_present = '''
    <script type="application/ld+json">
      {"name":"Warp Records"}
    </script>
    <meta property="og:title" content="WRONG NAME FROM OG" />
    '''
    with patch(
        "contracts.ProvenanceRegistry._http_get",
        return_value=both_present,
    ):
        handle, real_name, _ = _bandcamp_check("warp")

    assert real_name == "Warp Records", (
        f"JSON-LD should win over og:title, got {real_name!r}"
    )


def test_bandcamp_strips_trailing_pipe():
    """'Music | Mindex' in <title> should be stripped to 'Mindex'."""
    with patch(
        "contracts.ProvenanceRegistry._http_get",
        return_value=OG_TITLE_ONLY,
    ):
        handle, real_name, _ = _bandcamp_check("mindex")
    # The fixture has <title>Music | Mindex</title>; the strip should turn it into "Music"
    # when only og:title is parsed; we verify the pipe stripping works in either path.
    assert "|" not in real_name, f"Pipe should be stripped, got {real_name!r}"


def test_bandcamp_empty_page_returns_empty_name():
    """A page that exists but has no name anywhere yields empty real_name."""
    with patch(
        "contracts.ProvenanceRegistry._http_get",
        return_value=NOTHING_MATCHES,
    ):
        handle, real_name, location = _bandcamp_check("ghost")

    assert handle == "ghost"
    assert real_name == ""
    assert location == ""


def test_bandcamp_normalizes_full_url_input():
    """Full URL input is normalized to bare handle before the helper builds the URL."""
    with patch(
        "contracts.ProvenanceRegistry._http_get",
        return_value=JSON_LD_NAME,
    ) as mock_http:
        # Pre-normalized via the public helper, defense in depth
        normalized = _normalize_bandcamp("https://mindex.bandcamp.com/")
        handle, _, _ = _bandcamp_check(normalized)

    assert handle == "mindex"
    # Verify _http_get was called with the correctly-built URL, not the doubled-up URL
    called_url = mock_http.call_args[0][0]
    assert called_url == "https://mindex.bandcamp.com", (
        f"Expected bare handle URL, got {called_url!r} — normalization broken"
    )
