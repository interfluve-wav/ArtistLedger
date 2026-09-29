"""Certificate display authority — NOT VERIFIED can never present as verified.

Exercises frontend/cert-authority.js via Node so the steward requirement is
locked in: a negative finalized contract verdict (and fabricated-looking
evidence that would clear a lenient projection) must never produce a VRFD
seal, verified label, or replacement score.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERT_JS = ROOT / "frontend" / "cert-authority.js"


def _resolve(data: dict) -> dict:
    """Call resolveCertificateDisplay(data) in Node and return the JSON result."""
    payload = json.dumps(data)
    script = f"""
const cert = require({json.dumps(str(CERT_JS))});
const data = {payload};
process.stdout.write(JSON.stringify(cert.resolveCertificateDisplay(data)));
"""
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node failed ({proc.returncode}): {proc.stderr or proc.stdout}"
        )
    return json.loads(proc.stdout)


def _rich_unverified_evidence() -> dict:
    """Evidence that WOULD clear the lenient ≥60 projection but whose
    finalized on-chain verdict is NOT VERIFIED (score below 70)."""
    return {
        "verdict": "NOT VERIFIED",
        "score": 42,
        "matchCount": 2,
        "evidence": {
            "acoustid_matched": True,
            "spotify_artist_id": "fake-but-present",
            "apple_music_artist_id": "123456",
            "bandcamp_handle": "someone",
            "soundcloud_handle": "someone",
            "instagram_handle": "someone",
            "lastfm_scrobble_count": 500,
            "press_narrative_score": 3,
        },
    }


def test_cert_authority_module_loads():
    assert CERT_JS.is_file()
    out = _resolve({"verdict": "NOT VERIFIED", "score": 0, "matchCount": 0, "evidence": {}})
    assert out["ok"] is False


def test_negative_verdict_never_produces_vrfd_seal():
    """Steward: NOT VERIFIED can never produce a VRFD seal."""
    d = _rich_unverified_evidence()
    auth = _resolve(d)
    assert auth["friendlyWouldPass"] is True, (
        "fixture must clear lenient so we prove the seal still refuses VRFD"
    )
    assert auth["ok"] is False
    assert auth["seal"] == "—"
    assert auth["seal"] != "VRFD"
    assert "VRFD" not in auth["badge"]
    assert auth["badge"] == "NOT VERIFIED"


def test_negative_verdict_never_produces_verified_label():
    """Steward: NOT VERIFIED can never produce a verified label/subtitle."""
    auth = _resolve(_rich_unverified_evidence())
    assert auth["ok"] is False
    assert auth["subtitle"].startswith("not verified")
    assert not auth["subtitle"].startswith("verified")


def test_negative_verdict_never_replaces_on_chain_score():
    """Steward: NOT VERIFIED can never produce a replacement (lenient) score
    as the primary display score."""
    d = _rich_unverified_evidence()
    auth = _resolve(d)
    assert auth["displayScore"] == 42  # on-chain, not friendly
    assert auth["displayScore"] != auth["friendly"]
    assert auth["onChainScore"] == 42
    assert auth["friendly"] >= 60  # lenient would pass — still not used


def test_verified_verdict_still_shows_vrfd():
    """Positive control: VERIFIED still gets the seal and on-chain score."""
    auth = _resolve({
        "verdict": "VERIFIED",
        "score": 81,
        "matchCount": 2,
        "evidence": {"spotify_artist_id": "real", "apple_music_artist_id": "1"},
    })
    assert auth["ok"] is True
    assert auth["seal"] == "VRFD"
    assert auth["badge"] == "VRFD"
    assert auth["subtitle"].startswith("verified")
    assert auth["displayScore"] == 81


def test_fabricated_leader_style_evidence_with_negative_verdict_not_presented_verified():
    """Combined steward case: fabricated-looking rich leader evidence +
    negative finalized verdict must not present as verified anywhere in the
    certificate authority fields."""
    d = _rich_unverified_evidence()
    # Extra ownership flags a malicious leader might fabricate
    d["evidence"]["ownership_proof_soundcloud"] = True
    d["evidence"]["ownership_proof_youtube"] = True
    auth = _resolve(d)
    assert auth["ok"] is False
    assert auth["seal"] == "—"
    assert auth["onChainVerified"] is False
    assert auth["displayScore"] == d["score"]
    # scoreLine must say NOT VRFD, never VRFD as the outcome
    assert auth["scoreLine"].endswith("NOT VRFD")
    assert " · VRFD" not in auth["scoreLine"]


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-v", "--no-header"]))
