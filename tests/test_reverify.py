"""
Tests for v0.7.0 identity rotation — reverify() + wallet revocation.

Covers the wallet-migration flow: gates (already-current, missing proofs,
unverified old wallet, name mismatch, new wallet already holds an
identity), the ownership-proof requirement, the same-profile rule
(attacker-hijack guard), the Last.fm maturity floor, release re-pointing,
and revocation-aware views. Network-touching profile fetchers are mocked.
"""

import json
from unittest.mock import patch

import pytest

from contracts.ProvenanceRegistry import (
    Artist,
    DynArray,
    ProvenanceRegistry,
    Release,
    _profile_clusters_overlap,
    u256,
)

OLD = "0xOldWallet"
NEW = "0xNewWallet"
THIRD = "0xThirdWallet"
TOKEN = "ALVERIFY-NEW-1"
OLD_TOKEN = "ALVERIFY-OLD-1"


@pytest.fixture
def contract():
    return ProvenanceRegistry()


def _evidence_json(**overrides):
    base = {
        "bandcamp_handle": "burial",
        "soundcloud_handle": "burial",
        "instagram_handle": "burial",
        "verification_source_1": "",
        "verification_handle_1": "",
        "verification_source_2": "",
        "verification_handle_2": "",
    }
    base.update(overrides)
    return json.dumps(base)


def _verified_artist(wallet=OLD, *, name="Burial", score=80, evidence=None):
    return Artist(
        wallet=wallet,
        did="did:web:burial",
        name=name,
        verified_at=u256(1000),
        score=u256(score),
        evidence=evidence if evidence is not None else _evidence_json(),
        require_two_source=True,
    )


def _seed_verified(contract, wallet=OLD, **kw):
    artist = _verified_artist(wallet, **kw)
    contract.artists[wallet] = artist
    contract.verified_by_name[artist.name.strip().lower()] = wallet
    contract.verified_by_token[OLD_TOKEN] = wallet
    contract.identity_score[wallet] = u256(80)
    contract.identity_count[wallet] = u256(1)
    return artist


def _seed_release(contract, wallet=OLD, audio_hash=None):
    audio_hash = audio_hash or b"\x01" * 32
    contract.releases[audio_hash] = Release(
        artist=wallet,
        title="Compro",
        audio_hash=audio_hash,
        contributors=DynArray([wallet]),
        release_date=u256(1),
        anchored_at=u256(2000),
        contested=False,
    )
    contract.artist_releases[wallet] = [audio_hash]
    return audio_hash


# ─── Happy path ────────────────────────────────────────────────────────────


def test_reverify_migrates_identity_and_repoints_releases(contract):
    _seed_verified(contract)
    h = _seed_release(contract)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about page with {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})

    assert "Identity migrated" in result
    migrated = contract.artists[NEW]
    assert migrated.name == "Burial"
    assert migrated.did == "did:web:burial"
    assert int(migrated.score) == 80
    assert int(migrated.verified_at) == 2000
    # old wallet revoked (tombstoned)
    assert contract.revoked_wallets[OLD.lower()] is True
    assert int(contract.artists[OLD].score) == 0
    # identity indexes re-pointed
    assert contract.verified_by_name["burial"] == NEW
    assert contract.verified_by_token[TOKEN] == NEW
    # releases follow the identity
    assert contract.releases[h].artist == NEW
    assert h in contract.artist_releases[NEW]


def test_reverify_url_proof_variants(contract):
    """URL-form proof handles match stored bare handles."""
    _seed_verified(contract)
    with patch("contracts.ProvenanceRegistry._soundcloud_bio",
               return_value=f"bio {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        result = contract.reverify(
            OLD, "Burial", TOKEN,
            {"soundcloud": "https://soundcloud.com/burial"},
        )
    assert "Identity migrated" in result


# ─── Gates ─────────────────────────────────────────────────────────────────


def test_reverify_same_wallet_is_noop(contract):
    _seed_verified(contract)
    with patch.object(contract, "_sender", return_value=OLD):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "Already the current wallet" in result


def test_reverify_requires_token_and_proofs(contract):
    _seed_verified(contract)
    with patch.object(contract, "_sender", return_value=NEW):
        assert "Recovery requires" in contract.reverify(OLD, "Burial")
        assert "Recovery requires" in contract.reverify(OLD, "Burial", TOKEN)


def test_reverify_unverified_old_wallet_rejected(contract):
    _seed_verified(contract, score=40)
    with patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "not verified" in result


def test_reverify_name_mismatch_rejected(contract):
    _seed_verified(contract)
    with patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(
            OLD, "Somebody Completely Else", TOKEN, {"bandcamp": "burial"}
        )
    assert "Name does not match" in result


def test_reverify_new_wallet_already_verified_rejected(contract):
    _seed_verified(contract, wallet=OLD)
    _seed_verified(contract, wallet=NEW, name="Burial",
                   evidence=_evidence_json(
                       bandcamp_handle="burial", soundcloud_handle="burial",
                       instagram_handle="burial", verification_handle_1="burial"))
    with patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "already holds a verified identity" in result


def test_reverify_into_previously_revoked_wallet_allowed(contract):
    """A REVOKED (tombstoned, score-0) wallet is free real estate — it must
    not block recovery. Only an ACTIVE identity on the sender does."""
    contract.artists[NEW] = Artist(
        wallet=NEW, did="", name="", verified_at=u256(0), score=u256(0),
        evidence="{}", require_two_source=False,
    )
    contract.revoked_wallets[NEW.lower()] = True
    _seed_verified(contract, wallet=OLD)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "Identity migrated" in result
    assert contract.artists[NEW].name == "Burial"
    assert contract.revoked_wallets.get(OLD.lower()) is True


def test_reverify_round_trip_restores_views(contract):
    """A -> B -> back into A. The revoked_wallets marker on A is permanent,
    but the DERIVED state must follow the record: once a live identity is
    written there again, views read verified, never revoked."""
    _seed_verified(contract, wallet=OLD)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        assert "Identity migrated" in contract.reverify(OLD, "Burial", TOKEN,
                                                        {"bandcamp": "burial"})
    assert contract.get_artist(OLD) == {"verified": False, "revoked": True}

    # second recovery: B -> back into A
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}-2"), \
         patch.object(contract, "_sender", return_value=OLD), \
         patch.object(contract, "_now", return_value=3000):
        result = contract.reverify(NEW, "Burial", f"{TOKEN}-2",
                                   {"bandcamp": "burial"})
    assert "Identity migrated" in result
    a = contract.get_artist(OLD)
    assert a["verified"] is True and a["revoked"] is False
    by_name = contract.get_verified_by_name("Burial")
    assert by_name["wallet"] == OLD and by_name["verified"] is True
    assert contract.get_artist(NEW) == {"verified": False, "revoked": True}


def test_anchor_release_blocked_for_revoked_wallet(contract):
    """A revoked (stolen/lost) wallet must not keep write power: no
    anchoring under the dead identity, no audio-hash squatting."""
    _seed_verified(contract, wallet=OLD)
    h = _seed_release(contract, wallet=OLD)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})

    squat = b"\x03" * 32
    with patch.object(contract, "_sender", return_value=OLD):
        result = contract.anchor_release(squat, "Squat", [OLD], u256(1))
    assert result == "Not a verified artist"
    assert squat not in contract.releases
    # migrated identity can still anchor from the NEW wallet
    with patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2001):
        assert "Anchored" in contract.anchor_release(b"\x04" * 32, "Compro 2", [NEW], u256(2))
    assert contract.releases[h].artist == NEW  # old release still follows identity


def test_fresh_register_on_revoked_wallet_reads_live(contract):
    """Revoked wallet is free real estate for a NEW identity: once a live
    record is written there (register_artist's write), views must read
    verified — the stale marker must not shade them."""
    contract.artists[OLD] = Artist(
        wallet=OLD, did="", name="", verified_at=u256(0), score=u256(0),
        evidence="{}", require_two_source=False,
    )
    contract.revoked_wallets[OLD.lower()] = True
    # simulate register_artist's write of a fresh verified identity
    contract.artists[OLD] = _verified_artist(OLD, name="Burial")
    contract.verified_by_name["burial"] = OLD
    assert contract.get_artist(OLD)["verified"] is True
    assert contract.get_artist(OLD)["revoked"] is False


def test_reverify_unknown_wallet_rejected(contract):
    with patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "No verified artist on that wallet" in result


# ─── Proof requirements ────────────────────────────────────────────────────


def test_reverify_rejected_without_token_on_profile(contract):
    _seed_verified(contract)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value="no token here"), \
         patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "Recovery rejected" in result
    assert NEW not in contract.artists
    assert contract.verified_by_name["burial"] == OLD  # untouched


def test_reverify_rejects_replayed_registration_token(contract):
    """The registration token is PUBLIC (it sits in the artist's bio). It
    must not be a valid recovery credential — an attacker can read it off
    the profile, so reverify with that token must be refused before any
    fetch happens, even though the token genuinely appears in the profile
    text."""
    _seed_verified(contract)  # binds OLD_TOKEN -> OLD
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"bio with the old registration token {OLD_TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(OLD, "Burial", OLD_TOKEN,
                                   {"bandcamp": "burial"})
    assert "already used" in result
    assert NEW not in contract.artists
    assert contract.verified_by_name["burial"] == OLD
    assert contract.revoked_wallets.get(OLD.lower()) is None  # never revoked


def test_reverify_token_is_single_use(contract):
    """A successful migration consumes its token: a third wallet re-using
    the same token (still sitting in the profile text) cannot move the
    identity again."""
    _seed_verified(contract)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        result = contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "Identity migrated" in result

    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=THIRD):
        result = contract.reverify(NEW, "Burial", TOKEN, {"bandcamp": "burial"})
    assert "already used" in result
    assert THIRD not in contract.artists
    assert contract.verified_by_name["burial"] == NEW  # still at first new wallet


def test_reverify_same_profile_rule_blocks_hijack(contract):
    """Token on a DIFFERENT profile cluster than the original evidence
    cannot move the identity (attacker-hijack guard)."""
    _seed_verified(contract)  # evidence handles all "burial"
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(
            OLD, "Burial", TOKEN, {"bandcamp": "totally-different-band"}
        )
    assert "Recovery rejected" in result
    assert NEW not in contract.artists


def test_reverify_fresh_lastfm_account_fails_floor(contract):
    _seed_verified(contract, evidence=_evidence_json(
        verification_source_1="lastfm_url", verification_handle_1="burial"))
    with patch("contracts.ProvenanceRegistry._lastfm_profile_and_scrobbles",
               return_value=(f"journal {TOKEN}", 50)), \
         patch.object(contract, "_sender", return_value=NEW):
        result = contract.reverify(OLD, "Burial", TOKEN, {"lastfm": "burial"})
    assert "Recovery rejected" in result
    assert NEW not in contract.artists


def test_reverify_mature_lastfm_account_passes(contract):
    _seed_verified(contract, evidence=_evidence_json(
        verification_source_1="lastfm_url", verification_handle_1="burial"))
    with patch("contracts.ProvenanceRegistry._lastfm_profile_and_scrobbles",
               return_value=(f"journal {TOKEN}", 5000)), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        result = contract.reverify(OLD, "Burial", TOKEN, {"lastfm": "burial"})
    assert "Identity migrated" in result
    assert contract.verified_by_name["burial"] == NEW


# ─── Views after revocation ────────────────────────────────────────────────


def test_views_report_revocation(contract):
    _seed_verified(contract)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})

    assert contract.get_artist(NEW)["verified"] is True
    assert contract.get_artist(NEW)["revoked"] is False
    assert contract.get_artist(OLD) == {"verified": False, "revoked": True}

    by_name = contract.get_verified_by_name("Burial")
    assert by_name["wallet"] == NEW
    assert by_name["verified"] is True
    assert by_name["revoked"] is False

    # old token is honest about the move
    old_lookup = contract.get_verified_by_token(OLD_TOKEN)
    assert old_lookup["revoked"] is True
    assert old_lookup["verified"] is False

    new_lookup = contract.get_verified_by_token(TOKEN)
    assert new_lookup["wallet"] == NEW
    assert new_lookup["verified"] is True


def test_register_hints_reverify_for_revoked_token(contract):
    """A third wallet re-using a revoked identity's old token gets a
    recovery hint instead of a dead-end error."""
    _seed_verified(contract)
    with patch("contracts.ProvenanceRegistry._bandcamp_about",
               return_value=f"about {TOKEN}"), \
         patch.object(contract, "_sender", return_value=NEW), \
         patch.object(contract, "_now", return_value=2000):
        contract.reverify(OLD, "Burial", TOKEN, {"bandcamp": "burial"})

    with patch.object(contract, "_sender", return_value=THIRD):
        result = contract.register_artist(
            did="did:web:x",
            name="Burial",
            audio_hash=b"\x02" * 32,
            source_urls={},
            wallet=THIRD,
            ownership_token=OLD_TOKEN,
        )
    assert "reverify" in result


# ─── Same-profile helper (per-platform rule) ──────────────────────────────


def _stored_evidence(**kw):
    base = {
        "bandcamp_handle": "burial",
        "soundcloud_handle": "burial",
        "instagram_handle": "burial",
        "verification_source_1": "musicbrainz_url",
        "verification_handle_1": "mbid-123",
        "verification_source_2": "",
        "verification_handle_2": "",
    }
    base.update(kw)
    return base


def test_profile_clusters_overlap_same_platform():
    assert _profile_clusters_overlap(_stored_evidence(), {"bandcamp": "burial"})
    assert _profile_clusters_overlap(
        _stored_evidence(), {"bandcamp": "https://burial.bandcamp.com"}
    )
    assert _profile_clusters_overlap(
        _stored_evidence(), {"soundcloud": "https://soundcloud.com/burial"}
    )
    assert _profile_clusters_overlap(
        _stored_evidence(), {"soundcloud": "burial"}  # case-insensitive
    )


def test_profile_clusters_overlap_per_platform_blocks_squat():
    """Cross-platform squat: the SAME handle on a platform the victim never
    used must NOT match (that's the hijack the per-platform rule closes)."""
    assert not _profile_clusters_overlap(_stored_evidence(), {"youtube": "burial"})
    assert not _profile_clusters_overlap(_stored_evidence(), {"lastfm": "burial"})
    assert not _profile_clusters_overlap(_stored_evidence(), {"bandcamp": "someotherband"})
    assert not _profile_clusters_overlap(_stored_evidence(), {})
    assert not _profile_clusters_overlap({}, {"bandcamp": "burial"})


def test_profile_clusters_overlap_verification_source_platform():
    """lastfm/youtube have no stored handle — they only match when a stored
    verification source declares that platform."""
    stored = _stored_evidence(verification_source_1="lastfm_url",
                              verification_handle_1="burial")
    assert _profile_clusters_overlap(stored, {"lastfm": "burial"})
    stored2 = _stored_evidence(verification_source_1="youtube_url",
                               verification_handle_1="@burial")
    assert _profile_clusters_overlap(stored2, {"youtube": "@burial"})
    # without a declared source, lastfm can never be a recovery channel
    assert not _profile_clusters_overlap(_stored_evidence(), {"lastfm": "burial"})