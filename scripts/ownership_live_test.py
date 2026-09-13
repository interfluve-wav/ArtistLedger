#!/usr/bin/env python3
"""Live harness for Tier 2.6 ownership-proof readers.

Runs the EXACT contract functions (_soundcloud_bio, _youtube_description,
_lastfm_profile_and_scrobbles, _token_in_text) against real live profiles,
using the real key pools from .env. This is the off-chain functional test
for the channels before they're exercised on-chain via leader_collect.

Usage:
    python3 scripts/ownership_live_test.py \
        --token ALVERIFY-XXXX-YYYY \
        --soundcloud <handle> \
        --youtube <channel-about-url> \
        --lastfm <username>

Any channel can be omitted. Prints PASS/FAIL per channel.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "contracts"))

# --- load .env values (never printed) ---
def load_env():
    env = {}
    p = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

env = load_env()
lastfm_pool = [k for k in env.get("LASTFM_KEY_POOL", "").split(",") if k]

# import gl stubs first (same pattern as tests)
import types, json, urllib.request

class _RealResp:
    def __init__(self, body):
        self.body = body

def _real_web_get(url):
    """Real HTTP GET with a browser UA (off-chain harness only)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ArtistLedger-test/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return _RealResp(r.read())

gl_stub = types.ModuleType("gl")
gl_stub.nondet = types.SimpleNamespace(web=types.SimpleNamespace(get=_real_web_get),
                                       exec_prompt=lambda p: "0")
gl_stub.message_raw = {"datetime": "2026-09-13T00:00:00+00:00"}
gl_stub.message = types.SimpleNamespace(sender_address=None)
gl_stub.Contract = object
gl_stub.allow_storage = lambda cls: cls
def _pd(*a, **k):
    if len(a) == 1 and callable(a[0]):
        return a[0]
    return lambda fn: fn
gl_stub.public = types.SimpleNamespace(write=_pd, view=_pd)
sys.modules["gl"] = gl_stub

import importlib.util
spec = importlib.util.spec_from_file_location(
    "prov", os.path.join(os.path.dirname(__file__), "..", "contracts", "ProvenanceRegistry.py"))
prov = importlib.util.module_from_spec(spec)
sys.modules["prov"] = prov
prov.__dict__["gl"] = gl_stub
spec.loader.exec_module(prov)
# The contract's `from genlayer import *` rebinds gl to the real package
# during exec — re-inject the stub so helper calls hit the real HTTP layer.
prov.__dict__["gl"] = gl_stub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True, help="ALVERIFY-... token")
    ap.add_argument("--soundcloud", default="")
    ap.add_argument("--youtube", default="")
    ap.add_argument("--lastfm", default="")
    ap.add_argument("--artist", default="", help="artist name for Last.fm scrobble check")
    args = ap.parse_args()

    results = []

    if args.soundcloud:
        try:
            bio = prov._soundcloud_bio(args.soundcloud)
            ok = prov._token_in_text(bio, args.token)
            results.append((f"SoundCloud @{args.soundcloud}", ok, f"bio {len(bio)} chars, token {'found' if ok else 'NOT found'}"))
        except Exception as e:
            results.append((f"SoundCloud @{args.soundcloud}", False, f"ERROR: {e}"))

    if args.youtube:
        try:
            desc = prov._youtube_description(args.youtube)
            ok = prov._token_in_text(desc, args.token)
            results.append((f"YouTube {args.youtube[:60]}", ok, f"desc {len(desc)} chars, token {'found' if ok else 'NOT found'}"))
        except Exception as e:
            results.append(("YouTube", False, f"ERROR: {e}"))

    if args.lastfm:
        try:
            if not lastfm_pool:
                results.append(("Last.fm", False, "SKIPPED: no LASTFM_KEY_POOL in .env"))
            else:
                bio, scrobbles = prov._lastfm_profile_and_scrobbles(args.lastfm, lastfm_pool)
                ok = prov._token_in_text(bio, args.token)
                mature = scrobbles >= 200
                results.append((
                    f"Last.fm @{args.lastfm}",
                    ok and mature,
                    f"scrobbles={scrobbles} (≥200: {mature}), token {'found' if ok else 'NOT found'}"
                ))
        except Exception as e:
            results.append((f"Last.fm @{args.lastfm}", False, f"ERROR: {e}"))

    print("=" * 70)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}\n      {detail}")
    print("=" * 70)
    all_ok = all(ok for _, ok, _ in results) and len(results) > 0
    print("ALL CHANNELS PASS" if all_ok else "SOME CHANNELS FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()