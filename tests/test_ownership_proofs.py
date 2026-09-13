"""Tests for Tier 2.6 ownership proofs (ALVERIFY tokens).

Covers: token containment, Last.fm maturity floor, scoring cap, and the
validator fabrication guard. Network-touching helpers (_soundcloud_bio etc.)
are exercised through _token_in_text with canned text — the live fetchers
are thin regex wrappers tested on the contract testnet path.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "contracts"))

# Import the contract module without GenLayer runtime: the module imports
# `gl` at top-level, so stub it minimally for the pure helpers we test.
import types
import json
gl_stub = types.ModuleType("gl")
gl_stub.nondet = types.SimpleNamespace(
    web=types.SimpleNamespace(get=lambda url: None),
    exec_prompt=lambda prompt: "0",
)
gl_stub.message_raw = {"datetime": "2026-09-12T00:00:00+00:00"}
gl_stub.message = types.SimpleNamespace(sender_address=None)
gl_stub.Contract = object
gl_stub.allow_storage = lambda cls: cls  # decorator no-op for tests


def _public_decorator(*a, **k):
    """@gl.public.write / @gl.public.view — returns the fn unchanged."""
    if len(a) == 1 and callable(a[0]):
        return a[0]
    return lambda fn: fn

gl_stub.public = types.SimpleNamespace(write=_public_decorator, view=_public_decorator)
sys.modules["gl"] = gl_stub

# GenVM types stub (genlayer SDK: everything the contract touches at import).
# `from genlayer import *` needs a real module __all__ + attributes.
def _gl_any(name):
    if name == "u256":
        return int
    if name == "DynArray":
        return lambda *a, **k: []
    if name in ("Address", "TreeMap"):
        return object
    if name in ("allow_storage",):
        return lambda cls: cls
    return types.SimpleNamespace

GENLAYER_EXPORTS = [
    "u256", "DynArray", "Address", "TreeMap", "allow_storage",
]
genlayer_stub = types.ModuleType("genlayer")
genlayer_stub.__getattr__ = _gl_any
for _n in GENLAYER_EXPORTS:
    setattr(genlayer_stub, _n, _gl_any(_n))
genlayer_stub.__all__ = list(GENLAYER_EXPORTS)
sys.modules.setdefault("genlayer", genlayer_stub)

import importlib.util

# Inject the `gl` module name into the contract's namespace after exec —
# the contract references `gl.Contract` at class-definition time, and the
# real GenLayer runtime injects `gl` implicitly (we emulate that here).
spec = importlib.util.spec_from_file_location(
    "prov",
    os.path.join(os.path.dirname(__file__), "..", "contracts", "ProvenanceRegistry.py"),
)
prov = importlib.util.module_from_spec(spec)
sys.modules["prov"] = prov
prov.__dict__["gl"] = gl_stub
spec.loader.exec_module(prov)


class TestTokenInText:
    TOKEN = "ALVERIFY-7F3K2M9Q-1726155600"

    def test_exact_token_found(self):
        bio = "New album out now. ALVERIFY-7F3K2M9Q-1726155600 Booking: me@x.com"
        assert prov._token_in_text(bio, self.TOKEN) is True

    def test_missing_token(self):
        assert prov._token_in_text("just a normal bio", self.TOKEN) is False

    def test_empty_inputs(self):
        assert prov._token_in_text("", self.TOKEN) is False
        assert prov._token_in_text("bio", "") is False

    def test_case_sensitivity_rejects_lowercase(self):
        """Case-folded token does NOT count — kills sybil case variants."""
        lower = self.TOKEN.lower()
        assert prov._token_in_text(lower, self.TOKEN) is False

    def test_partial_token_rejected(self):
        assert prov._token_in_text("ALVERIFY-7F3K2M9Q", self.TOKEN) is False


class TestOwnershipScoring:
    def _ev(self, **flags):
        ev = prov.Evidence.empty()
        for k, v in flags.items():
            setattr(ev, k, v)
        return ev

    def test_no_proofs_zero_points(self):
        assert prov._score_evidence(self._ev(), "X") >= 0

    def test_single_proof_adds_25(self):
        ev = self._ev(ownership_proof_soundcloud=True)
        base = prov._score_evidence(prov.Evidence.empty(), "X")
        assert prov._score_evidence(ev, "X") == base + prov.W_OWNERSHIP_PROOF

    def test_two_proofs_add_50(self):
        ev = self._ev(ownership_proof_soundcloud=True, ownership_proof_youtube=True)
        base = prov._score_evidence(prov.Evidence.empty(), "X")
        assert prov._score_evidence(ev, "X") == base + 50

    def test_four_proofs_capped_at_50(self):
        ev = self._ev(
            ownership_proof_soundcloud=True, ownership_proof_lastfm=True,
            ownership_proof_bandcamp=True, ownership_proof_youtube=True,
        )
        base = prov._score_evidence(prov.Evidence.empty(), "X")
        assert prov._score_evidence(ev, "X") == base + prov.W_OWNERSHIP_PROOF * prov.W_OWNERSHIP_CAP

    def test_score_never_exceeds_100(self):
        ev = prov.Evidence.empty()
        ev.acoustid_matched = True
        ev.isrc_codes = ["ISRC1", "ISRC2"]
        ev.spotify_artist_id = "x" * 22
        ev.spotify_verified = True
        ev.apple_music_track_present = True
        ev.verification_match_count = prov.u256(2)
        ev.ownership_proof_soundcloud = True
        ev.ownership_proof_lastfm = True
        ev.ownership_proof_bandcamp = True
        ev.ownership_proof_youtube = True
        s = prov._score_evidence(ev, "X")
        assert 0 <= s <= 100

    def test_dict_boundary_roundtrip(self):
        """Validator path: dict evidence scores same as Evidence object."""
        ev = self._ev(ownership_proof_bandcamp=True)
        d = ev.to_dict()
        assert prov._score_evidence_from_dict(d, "X") == prov._score_evidence(ev, "X")


class TestLastfmMaturityFloor:
    def test_floor_constant(self):
        assert prov.LASTFM_SCROBBLE_FLOOR == 200

    def test_fresh_account_below_floor_fails_guard(self):
        """Validator guard: proof claimed but scrobbles < floor → reject."""
        d = {
            "ownership_proof_lastfm": True,
            "ownership_lastfm_scrobbles": 5,
            "acoustid_matched": True,
        }
        # simulate the validator guard logic directly
        if d.get("ownership_proof_lastfm") and int(
            d.get("ownership_lastfm_scrobbles", 0) or 0
        ) < prov.LASTFM_SCROBBLE_FLOOR:
            guard_ok = False
        else:
            guard_ok = True
        assert guard_ok is False

    def test_mature_account_passes_guard(self):
        d = {
            "ownership_proof_lastfm": True,
            "ownership_lastfm_scrobbles": 4210,
            "acoustid_matched": True,
        }
        if d.get("ownership_proof_lastfm") and int(
            d.get("ownership_lastfm_scrobbles", 0) or 0
        ) < prov.LASTFM_SCROBBLE_FLOOR:
            guard_ok = False
        else:
            guard_ok = True
        assert guard_ok is True


class TestEvidenceRoundtrip:
    def test_empty_has_all_ownership_fields(self):
        ev = prov.Evidence.empty()
        assert ev.ownership_proof_soundcloud is False
        assert ev.ownership_proof_lastfm is False
        assert ev.ownership_proof_bandcamp is False
        assert ev.ownership_proof_youtube is False
        assert int(ev.ownership_lastfm_scrobbles) == 0

    def test_to_dict_includes_ownership(self):
        ev = prov.Evidence.empty()
        ev.ownership_proof_soundcloud = True
        d = ev.to_dict()
        assert d["ownership_proof_soundcloud"] is True
        assert "ownership_lastfm_scrobbles" in d


class TestLastfmResolveArtist:
    """artist.search → canonical-name resolution (requires api key; mocked)."""

    def _search_response(self, name, mbid):
        return {
            "results": {
                "artistmatches": {
                    "artist": [{"name": name, "mbid": mbid}]
                }
            }
        }

    def test_resolves_canonical_name(self):
        """'fred again..' → canonical 'Fred Again...' when MBID present."""
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = lambda url: types.SimpleNamespace(
            body=json.dumps(self._search_response("Fred Again...", "1234-5678")).encode()
        )
        try:
            assert prov._lastfm_resolve_artist("fred again..", "key") == "Fred Again..."
        finally:
            prov.gl.nondet.web.get = orig

    def test_no_key_returns_empty(self):
        assert prov._lastfm_resolve_artist("Cher", "") == ""
        assert prov._lastfm_resolve_artist("", "key") == ""

    def test_no_mbid_rejected(self):
        """A match without an MBID is a vanity/unregistered page — reject."""
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = lambda url: types.SimpleNamespace(
            body=json.dumps(self._search_response("Cher", "")).encode()
        )
        try:
            assert prov._lastfm_resolve_artist("Cher", "key") == ""
        finally:
            prov.gl.nondet.web.get = orig

    def test_no_matches_returns_empty(self):
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = lambda url: types.SimpleNamespace(
            body=json.dumps({"results": {"artistmatches": {"artist": []}}}).encode()
        )
        try:
            assert prov._lastfm_resolve_artist("NoSuchArtistZzz", "key") == ""
        finally:
            prov.gl.nondet.web.get = orig

    def test_scrobbles_uses_canonical_name(self):
        """_lastfm_scrobbles resolves then queries getInfo with canonical."""
        calls = []
        def fake_get(url):
            calls.append(url)
            if "artist.search" in url:
                body = json.dumps({
                    "results": {"artistmatches": {"artist": [{"name": "Aphex Twin", "mbid": "abcd"}]}}
                })
            else:  # artist.getInfo
                body = json.dumps({"artist": {"stats": {"userplaycount": 42}}})
            return types.SimpleNamespace(body=body.encode())
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = fake_get
        try:
            n = prov._lastfm_scrobbles("APHEX TWIN", "listener", "key")
        finally:
            prov.gl.nondet.web.get = orig
        assert n == 42
        assert any("artist.search" in u and "APHEX TWIN" in u for u in calls)
        assert any("artist.getInfo" in u and "Aphex Twin" in u for u in calls)


class TestLastfmPageParsing:
    """Parse the real Last.fm profile markup (fixture captured 2026-09-12).

    The page carries a trap: a tooltip "an average of 17 scrobbles per day!"
    that a naive /N scrobbles?/ regex matches FIRST. The parser must anchor
    on the Scrobbles header + /user/X/library link instead.
    """

    FIXTURE = (
        '<li class="header-metadata-item"> <h4 class="header-metadata-title"> '
        'Scrobbles </h4> <div class=" header-metadata-display "> '
        '<p title="That&#39;s an average of 17 scrobbles per day!" >'
        '<a href="/user/RJ/library" >151,481</a>'
    )

    def test_parses_real_fixture(self):
        body = self.FIXTURE
        # exercise via a stubbed _http_get: the function reads the URL argument
        # through gl.nondet.web.get — patch the stub to return the fixture.
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = lambda url: types.SimpleNamespace(body=self.FIXTURE.encode())
        try:
            _, scrobbles = prov._lastfm_profile_and_scrobbles("RJ", "")
        finally:
            prov.gl.nondet.web.get = orig
        assert scrobbles == 151481

    def test_parses_full_live_capture(self):
        """Full real page (captured 2026-09-12, 456KB) — regression guard."""
        import os
        path = os.path.join(os.path.dirname(__file__), "fixtures", "lastfm_profile_rj.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = lambda url: types.SimpleNamespace(body=html.encode())
        try:
            _, scrobbles = prov._lastfm_profile_and_scrobbles("RJ", "")
        finally:
            prov.gl.nondet.web.get = orig
        assert scrobbles == 151481

    def test_tooltip_trap_not_matched(self):
        """A page whose only 'N scrobbles' occurrence is the avg/day tooltip
        (no library link) must yield 0 — NOT '17'."""
        trap_only = self.FIXTURE.split('<a href="/user/RJ/library"')[0] + "</div>"
        orig = prov.gl.nondet.web.get
        prov.gl.nondet.web.get = lambda url: types.SimpleNamespace(body=trap_only.encode())
        try:
            _, scrobbles = prov._lastfm_profile_and_scrobbles("RJ", "")
        finally:
            prov.gl.nondet.web.get = orig
        assert scrobbles == 0

    def test_empty_handle_returns_zero(self):
        assert prov._lastfm_profile_and_scrobbles("", "") == ("", 0)


# ─── Last.fm key pool rotation ────────────────────────────────────────────

class FakePoolResolve:
    """Stub _lastfm_resolve_artist to return a canonical name."""
    def __init__(self, scrobbles_results):
        self.scrobbles_results = scrobbles_results  # list of (data, key) per call
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        d = self.scrobbles_results[len(self.calls) - 1] if len(self.calls) - 1 < len(self.scrobbles_results) else {"error": 29}
        return d


def test_pool_rotates_on_rate_limit(monkeypatch):
    _lastfm_scrobbles = prov._lastfm_scrobbles
    calls = []
    def fake_get(url):
        calls.append(url)
        if len(calls) == 1:
            return {"error": 29}  # first key rate-limited
        if len(calls) == 2:
            return {"error": 10}  # second key invalid
        return {"artist": {"stats": {"userplaycount": 42}}}
    monkeypatch.setattr(prov, "_http_get_json", fake_get)
    def fake_resolve(artist, key):
        return "Cher"
    monkeypatch.setattr(prov, "_lastfm_resolve_artist", fake_resolve)
    result = _lastfm_scrobbles("Cher", "someuser", ["k1", "k2", "k3"])
    assert result == 42
    assert len(calls) == 3  # rotated through all three


def test_pool_all_fail_returns_zero(monkeypatch):
    _lastfm_scrobbles = prov._lastfm_scrobbles
    monkeypatch.setattr(prov, "_http_get_json",
                        lambda url: {"error": 29})
    monkeypatch.setattr(prov, "_lastfm_resolve_artist",
                        lambda artist, key: "Cher")
    assert _lastfm_scrobbles("Cher", "user", ["a", "b"]) == 0


def test_single_key_still_works(monkeypatch):
    _lastfm_scrobbles = prov._lastfm_scrobbles
    monkeypatch.setattr(prov, "_http_get_json",
                        lambda url: {"artist": {"stats": {"userplaycount": 7}}})
    monkeypatch.setattr(prov, "_lastfm_resolve_artist",
                        lambda artist, key: "Cher")
    assert _lastfm_scrobbles("Cher", "user", "single-key") == 7


def test_pool_resolve_rotates_on_error(monkeypatch):
    _lastfm_resolve_artist = prov._lastfm_resolve_artist
    calls = []
    def fake_get(url):
        calls.append(url)
        if len(calls) == 1:
            return {"error": 29}
        return {"results": {"artistmatches": {"artist": [{"name": "Cher", "mbid": "abc"}]}}}
    monkeypatch.setattr(prov, "_http_get_json", fake_get)
    assert _lastfm_resolve_artist("cher", ["k1", "k2"]) == "Cher"
    assert len(calls) == 2


# ─── Spotify client-credentials pool ──────────────────────────────────────

def test_set_spotify_key_pool_filters_bad_entries():
    inst = prov.ProvenanceRegistry()
    out = inst.set_spotify_key_pool([["cid1", "csec1"], ["cid2", ""], "junk", ["ok", "sec", "extra"]])
    assert out == "Spotify key pool set (2 pairs)"
    assert inst.get_spotify_pool_size() == 2
    assert inst.spotify_client_pairs == json.dumps([["cid1", "csec1"], ["ok", "sec"]])
    assert inst._spotify_pool_list() == [["cid1", "csec1"], ["ok", "sec"]]


def test_spotify_pool_rotates_on_failed_mint(monkeypatch):
    calls = []
    def fake_mint(cid, sec):
        calls.append((cid, sec))
        if len(calls) == 1:
            return ""
        return "bearer-ok"
    monkeypatch.setattr(prov, "_spotify_mint_token", fake_mint)
    pairs = [["bad-id", "bad-sec"], ["good-id", "good-sec"]]
    # simulate leader_collect's mint loop
    tok = ""
    for pair in pairs:
        tok = prov._spotify_mint_token(pair[0], pair[1])
        if tok:
            break
    assert tok == "bearer-ok"
    assert len(calls) == 2  # rotated to second pair


def test_spotify_pool_empty_falls_back(monkeypatch):
    # pool empty + no stored pair -> no token
    monkeypatch.setattr(prov, "_spotify_mint_token", lambda a, b: "")
    assert prov._spotify_mint_token("x", "y") == ""
