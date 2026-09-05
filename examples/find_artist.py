#!/usr/bin/env python3
"""
find_artist.py — pre-enrich artist URLs before calling register_artist().

Takes 1+ known artist URLs and follows cross-references on each platform
(Discogs, iTunes, Bandcamp, MusicBrainz, YouTube) to discover every other
URL the artist has online.

No paid APIs. No Spotify token. No Firecrawl. Just free public endpoints.

Usage:
    python3 find_artist.py --name "Skee Mask" --seed "https://open.spotify.com/artist/2qwi0hBvI2GrbkurOnw3hZ"
    python3 find_artist.py --name "Burial" --seed "https://www.bandcamp.com/burial" --seed "https://www.discogs.com/artist/62418"
    python3 find_artist.py --name "Skee Mask" --seed "..."  --json  # raw dict

Why this design: MusicBrainz covers ~10% of working artists well (electronic,
DJ, niche). Discogs covers ~70% (every major, every indie, every vinyl-era
artist). iTunes Search is universal for any artist on Apple Music. By using
user-provided URLs as seeds and following each platform's own
external_urls / url-rels / bandcamp-page-crawling, we get to 90%+ coverage
without any paid API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import quote as _urlquote
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    sys.exit("requests required: pip install requests")

MB_USER_AGENT = os.getenv(
    "MB_USER_AGENT",
    "provenance-registry/0.3.4 (https://github.com/dembow-ai/provenance-registry)",
)
TIMEOUT = 10
BANDCAMP_HTML_MAX = 200_000  # bytes to read before parsing

# ── low-level HTTP ───────────────────────────────────────────────────────

def _get(url: str, *, headers: dict | None = None) -> dict | None:
    try:
        r = requests.get(url, headers=headers or {}, timeout=TIMEOUT)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith(
            ("application/json", "text/javascript")
        ):
            return r.json()
    except Exception:
        pass
    return None


def _get_text(url: str, *, headers: dict | None = None, limit: int | None = None) -> str:
    try:
        r = requests.get(
            url,
            headers=headers or {},
            timeout=TIMEOUT,
            stream=True,
        )
        if r.status_code != 200:
            return ""
        text = ""
        for chunk in r.iter_content(chunk_size=8192, decode_unicode=True):
            text += chunk
            if limit and len(text) > limit:
                break
        return text
    except Exception:
        return ""


def _head_ok(url: str) -> bool:
    try:
        r = requests.head(url, allow_redirects=True, timeout=TIMEOUT)
        return r.status_code == 200
    except Exception:
        return False


# ── seed extraction: pull known IDs from URLs ───────────────────────────

def _spotify_id(url_or_id: str) -> str:
    if not url_or_id:
        return ""
    m = re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]+)", url_or_id)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9]{20,25}$", url_or_id):
        return url_or_id
    return ""


def _apple_artist_id(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"music\.apple\.com/[^/]+/artist/[^/]+/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"music\.apple\.com/[^/]+/artist/(\d+)", url)
    if m:
        return m.group(1)
    return ""


def _discogs_artist_id(url_or_id: str) -> str:
    if not url_or_id:
        return ""
    m = re.search(r"discogs\.com/(?:artist|artist/)([^/?]+)", url_or_id)
    if m and m.group(1).isdigit():
        return m.group(1)
    if url_or_id.isdigit():
        return url_or_id
    return ""


def _bandcamp_handle(url: str) -> str:
    if not url:
        return ""
    # Match the canonical <handle>.bandcamp.com (NOT www.bandcamp.com/foo)
    m = re.search(r"^https?://([\w-]+)\.bandcamp\.com/?$", url)
    if m:
        return m.group(1)
    p = urlparse(url)
    # Only treat /<handle> as a bandcamp handle if the host is bandcamp.com
    # AND the path is a single segment that is NOT a known non-artist page.
    if p.netloc in ("bandcamp.com", "www.bandcamp.com") and p.path.startswith("/"):
        parts = [s for s in p.path.split("/") if s]
        NON_ARTIST = {"discover", "signup", "login", "fans", "artists", "wishlist",
                      "cart", "search", "feed", "releases", "daily", "genre",
                      "location", "tag", "album", "track", "label", "app"}
        if len(parts) == 1 and parts[0].lower() not in NON_ARTIST:
            return parts[0]
    return ""


def _instagram_handle(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"instagram\.com/([\w\.]+)", url)
    if m:
        return m.group(1)
    return ""


def _twitter_handle(url_or_handle: str) -> str:
    if not url_or_handle:
        return ""
    m = re.search(r"twitter\.com/([\w]+)", url_or_handle)
    if m:
        return m.group(1)
    m = re.search(r"x\.com/([\w]+)", url_or_handle)
    if m:
        return m.group(1)
    return ""


def _youtube_handle(url: str) -> str:
    if not url:
        return ""
    m = re.search(r"youtube\.com/@([\w\.-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"youtube\.com/channel/([\w-]+)", url)
    if m:
        return m.group(1)
    return ""


# ── cross-reference APIs ─────────────────────────────────────────────────

def _discogs_enrich(seed_id: str) -> dict:
    """Pull every URL the Discogs artist profile links to. Returns partial dict."""
    out: dict = {}
    if not seed_id:
        return out
    data = _get(
        f"https://api.discogs.com/artists/{seed_id}",
        headers={"User-Agent": MB_USER_AGENT},
    )
    if not data:
        return out
    name = data.get("name", "")
    profile = data.get("profile", "")
    out["discogs_artist_id"] = seed_id
    out["discogs_name"] = name
    out["discogs_profile"] = profile
    out["discogs_url_count"] = len(data.get("urls", []))
    for url in data.get("urls", []):
        _route_discogs_url(out, url)
    return out


def _route_discogs_url(out: dict, url: str) -> None:
    if "open.spotify.com/artist/" in url:
        out.setdefault("spotify_artist_id", _spotify_id(url))
    elif "music.apple.com" in url:
        out.setdefault("apple_music_url", url)
    elif ".bandcamp.com" in url:
        out.setdefault("bandcamp", _bandcamp_handle(url))
    elif "soundcloud.com/" in url:
        m = re.search(r"soundcloud\.com/([\w-]+)", url)
        if m:
            out.setdefault("soundcloud", m.group(1))
    elif "instagram.com/" in url:
        out.setdefault("instagram", _instagram_handle(url))
    elif "twitter.com/" in url or "x.com/" in url:
        out.setdefault("twitter_handle", _twitter_handle(url))
    elif "youtube.com/" in url:
        out.setdefault("youtube_channel", _youtube_handle(url))
    elif "last.fm/" in url:
        m = re.search(r"last\.fm/music/([\w\+\%]+)", url)
        if m:
            out.setdefault("lastfm_user", m.group(1))
    elif "boomkat.com" in url:
        out.setdefault("boomkat_url", url)
    elif "rateyourmusic.com" in url:
        out.setdefault("rateyourmusic_url", url)
    elif "ra.co/" in url:
        out.setdefault("residentadvisor_url", url)
    elif "facebook.com/" in url:
        out.setdefault("facebook_url", url)
    elif "tidal.com/" in url:
        out.setdefault("tidal_url", url)
    elif "deezer.com/" in url:
        out.setdefault("deezer_url", url)


def _itunes_search(name: str) -> dict:
    """Public iTunes Search. Returns Apple Music artist URL + sometimes the Spotify link."""
    out: dict = {}
    if not name:
        return out
    data = _get(
        f"https://itunes.apple.com/search?term={_urlquote(name)}&entity=musicArtist&limit=3"
    )
    if not data or not data.get("results"):
        return out
    for r in data["results"]:
        if r.get("wrapperType") == "artist":
            out.setdefault("apple_music_url", r.get("artistLinkUrl", ""))
            out.setdefault("apple_music_artist_id", str(r.get("artistId", "")))
            break
    return out


def _itunes_artist_albums(artist_id: str) -> dict:
    """Pull an artist's iTunes albums to surface cross-references in track metadata."""
    out: dict = {}
    if not artist_id:
        return out
    data = _get(
        f"https://itunes.apple.com/lookup?id={artist_id}&entity=album&limit=3"
    )
    if not data or not data.get("results"):
        return out
    out["itunes_album_count"] = data.get("resultCount", 0)
    return out


def _bandcamp_html_crawl(handle: str) -> dict:
    """Bandcamp public page crawl. Find links to other platforms via the page's
    custom HTML 'artist-page' links and the musicbrainz-style links footer."""
    out: dict = {}
    if not handle:
        return out
    url = f"https://{handle}.bandcamp.com"
    html = _get_text(url, limit=BANDCAMP_HTML_MAX)
    if not html:
        return out
    out["bandcamp"] = handle
    for href in re.findall(r'href="([^"]+)"', html):
        _route_discogs_url(out, href)
    if "twitter.com/" in html or "x.com/" in html:
        m = re.search(r'(?:twitter\.com|x\.com)/([\w]+)', html)
        if m and "twitter_handle" not in out:
            out["twitter_handle"] = m.group(1)
    return out


def _musicbrainz_fallback(name: str) -> dict:
    """Last-resort MB lookup. Returns what we can from MB URL-relations."""
    out: dict = {}
    if not name:
        return out
    data = _get(
        f"https://musicbrainz.org/ws/2/artist/?query={_urlquote(name)}&fmt=json&limit=1",
        headers={"User-Agent": MB_USER_AGENT},
    )
    if not data or not data.get("artists"):
        return out
    mbid = data["artists"][0]["id"]
    rels_data = _get(
        f"https://musicbrainz.org/ws/2/artist/{mbid}?inc=url-rels&fmt=json",
        headers={"User-Agent": MB_USER_AGENT},
    )
    if not rels_data:
        out["musicbrainz_id"] = mbid
        return out
    out["musicbrainz_id"] = mbid
    for rel in rels_data.get("relations", []):
        url = rel.get("url", {}).get("resource", "")
        if url:
            _route_discogs_url(out, url)
    return out


# ── 200-check fallback for handles the user provided but we couldn't enrich ──

def _verify_handle_present(handle: str) -> bool:
    return _head_ok(f"https://{handle}.bandcamp.com") if handle else False


# ── main find_artist ─────────────────────────────────────────────────────

def find_artist(name: str, seeds: list[str]) -> dict:
    """Aggregate every URL we can find for `name` given `seeds` (known URLs/handles).

    `seeds` is a list of strings; each string is a URL or bare ID. The function
    walks each seed through the appropriate platform's API and routes results
    into a single source_urls dict that the contract consumes.

    Returns the dict even if no seeds are provided (falls back to iTunes + MB).
    """
    source_urls: dict = {
        "bandcamp": "",
        "soundcloud": "",
        "instagram": "",
        "lastfm_user": "",
        "spotify_artist_id": "",
        "apple_music_url": "",
        "apple_music_artist_id": "",
        "twitter_handle": "",
        "youtube_channel": "",
        "discogs_artist_id": "",
        "personal_url": "",
        "boomkat_url": "",
        "rateyourmusic_url": "",
        "residentadvisor_url": "",
        "facebook_url": "",
        "tidal_url": "",
        "deezer_url": "",
        "musicbrainz_id": "",
        "discogs_url_count": 0,
        "itunes_album_count": 0,
        # what the contract's leader_collect actually consumes today:
        "release_title": "",
    }

    # 1. Walk seeds, route through platform APIs
    seen_discogs_ids: set[str] = set()
    for seed in seeds:
        if not seed:
            continue
        # Discogs seed?
        did = _discogs_artist_id(seed)
        if did and did not in seen_discogs_ids:
            seen_discogs_ids.add(did)
            for k, v in _discogs_enrich(did).items():
                if v and (not source_urls.get(k) or k == "discogs_url_count"):
                    source_urls[k] = v
        # Spotify seed? (no token = no enrichment, but record the ID)
        sid = _spotify_id(seed)
        if sid:
            source_urls["spotify_artist_id"] = sid
        # Bandcamp seed?
        bch = _bandcamp_handle(seed)
        if bch and _verify_handle_present(bch):
            for k, v in _bandcamp_html_crawl(bch).items():
                if v and not source_urls.get(k):
                    source_urls[k] = v
        # Instagram/Twitter/YouTube seeds (no enrichment APIs; just record)
        ig = _instagram_handle(seed)
        if ig:
            source_urls["instagram"] = ig
        tw = _twitter_handle(seed)
        if tw:
            source_urls["twitter_handle"] = tw
        yh = _youtube_handle(seed)
        if yh:
            source_urls["youtube_channel"] = yh

    # 2. iTunes Search (public, free, universal for any artist on Apple Music)
    if not source_urls.get("apple_music_artist_id"):
        for k, v in _itunes_search(name).items():
            if v and not source_urls.get(k):
                source_urls[k] = v

    # 3. iTunes album count (cross-reference: artist has releases on Apple Music)
    if source_urls.get("apple_music_artist_id"):
        for k, v in _itunes_artist_albums(source_urls["apple_music_artist_id"]).items():
            if v and not source_urls.get(k):
                source_urls[k] = v

    # 4. MusicBrainz last-resort fallback
    if not source_urls.get("musicbrainz_id"):
        for k, v in _musicbrainz_fallback(name).items():
            if v and not source_urls.get(k):
                source_urls[k] = v

    return source_urls


# ── DISCO step-5 shape (Layer 4) ────────────────────────────────────────

# The DISCO signup flow asks the artist to claim up to two of 13 source
# types. Map the enriched fields find_artist discovers onto that enum so
# the output can be pasted into register_artist() directly.
DISCO_ENUM_KEYS = {
    # disco enum type   -> (url-field in source_urls,    handle-field)
    # Field names must match find_artist()'s output dict exactly.
    "spotify":          ("",                             "spotify_artist_id"),
    "apple_music":      ("apple_music_url",              "apple_music_artist_id"),
    "soundcloud":       ("",                             "soundcloud"),
    "bandcamp":         ("",                             "bandcamp"),
    "instagram":        ("",                             "instagram"),
    "tiktok":           ("",                             ""),  # not discoverable via free APIs
    "tidal":            ("tidal_url",                    ""),
    "twitter":          ("",                             "twitter_handle"),
    "youtube":          ("",                             "youtube_channel"),
    "facebook":         ("facebook_url",                 ""),
    "website":          ("personal_url",                 ""),
    "lastfm":           ("",                             "lastfm_user"),
    "ipi":              ("",                             ""),  # needs PRO lookup, not discoverable
}

# Strength order for picking the two best cross-reference targets.
# Only types the contract's _verify_claimed_source can actually dispatch
# on (Spotify/Apple/Bandcamp/SoundCloud/Instagram/Last.fm get real
# checks; TikTok/Tidal/FB/website too since Layer 2). Tier-1 real
# verification sources first — they score highest in the contract.
_SOURCE_STRENGTH = [
    "spotify", "apple_music",
    "bandcamp", "soundcloud", "lastfm",
    "instagram", "tiktok", "tidal", "facebook", "website",
    "twitter", "youtube",
]


def _disco_mode(source_urls: dict) -> dict:
    """Emit the DISCO step-5 shape: every enum key -> {url, handle, found}.

    This is what the frontend form step 5 asks for. ``found`` is True
    when find_artist actually discovered a value (vs. the artist having
    to claim it themselves).
    """
    out = {}
    for enum_type, (url_field, handle_field) in DISCO_ENUM_KEYS.items():
        url = source_urls.get(url_field, "") if url_field else ""
        handle = source_urls.get(handle_field, "") if handle_field else ""
        out[enum_type] = {
            "url": url,
            "handle": handle,
            "found": bool(url or handle),
        }
    return out


def _two_source_report(source_urls: dict) -> dict:
    """Pick the two strongest discovered sources for verification_source_1/2.

    Returns the exact args to pass to register_artist() plus a plain-
    English explanation of why those two were chosen.
    """
    candidates = []
    for enum_type in _SOURCE_STRENGTH:
        entry = _disco_entry(source_urls, enum_type)
        if entry["found"]:
            candidates.append((enum_type, entry))
    picks = candidates[:2]
    if not picks:
        return {
            "verification_source_1": "", "verification_handle_1": "",
            "verification_source_2": "", "verification_handle_2": "",
            "explanation": "No sources discovered. Provide seeds or set up "
                           "API keys to enrich.",
        }
    first = picks[0]
    second = picks[1] if len(picks) > 1 else ("", {"url": "", "handle": ""})
    report = {
        "verification_source_1": first[0],
        "verification_handle_1": first[1]["handle"] or first[1]["url"],
    }
    if second and second[0]:
        report.update({
            "verification_source_2": second[0],
            "verification_handle_2": second[1]["handle"] or second[1]["url"],
        })
    else:
        report.update({"verification_source_2": "", "verification_handle_2": ""})
    names = [p[0] for p in picks if p[0]]
    report["explanation"] = (
        f"Best cross-reference pair: {' + '.join(names)}. "
        f"Both resolve independently and their metadata should name-match "
        f"the artist, giving W_TWO_SOURCE_MATCH (+15). "
        f"Pass require_two_source=True (default) to enforce both."
    )
    return report


def _disco_entry(source_urls: dict, enum_type: str) -> dict:
    url_field, handle_field = DISCO_ENUM_KEYS[enum_type]
    url = source_urls.get(url_field, "") if url_field else ""
    handle = source_urls.get(handle_field, "") if handle_field else ""
    return {"url": url, "handle": handle, "found": bool(url or handle)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Find every URL an artist has online, given 1+ known URLs as seeds."
    )
    ap.add_argument("--name", required=True, help="Artist name (for iTunes/MB fallbacks)")
    ap.add_argument(
        "--seed", action="append", default=[],
        help="Known URL or ID (Spotify, Bandcamp, Discogs, Instagram, Twitter, YouTube). "
             "Pass multiple times for multiple seeds.",
    )
    ap.add_argument("--json", action="store_true", help="Print raw dict only")
    ap.add_argument(
        "--disco-mode", action="store_true",
        help="Emit DISCO step-5 shape: every enum key -> {url, handle, found}",
    )
    ap.add_argument(
        "--two-source-report", action="store_true",
        help="Print the two strongest discovered sources as verification_source_1/2 "
             "args for register_artist()",
    )
    args = ap.parse_args()

    if not args.seed:
        print(
            "  ⚠ No --seed provided; will fall back to iTunes + MusicBrainz only.",
            file=sys.stderr,
        )
    print(f"Looking up '{args.name}' with {len(args.seed)} seed(s) ...", file=sys.stderr)
    urls = find_artist(args.name, args.seed)

    if args.disco_mode:
        print(json.dumps(_disco_mode(urls), indent=2))
        return
    if args.two_source_report:
        print(json.dumps(_two_source_report(urls), indent=2))
        return

    found = {k: v for k, v in urls.items() if v}
    missing = {k: v for k, v in urls.items() if not v}
    print(json.dumps(urls, indent=2))
    if not args.json:
        print(f"\n  ✓ Found: {len(found)} fields populated", file=sys.stderr)
        print(f"  ✗ Empty: {len(missing)} fields", file=sys.stderr)


if __name__ == "__main__":
    main()
