"""
Unit tests for OnChainProvenanceRegistry state transitions.

These tests run against the GenLayer VM with mocked web calls and mocked
LLM responses. They verify:

  - State transitions (verified/not verified, anchored/not anchored,
    contested/not contested)
  - Edge cases (re-anchoring same hash, dispute on own release, etc.)
  - The read-only view methods
  - The reputation penalty flow when a dispute is upheld

Run with:
    pytest tests/test_provenance.py -v
"""

from unittest.mock import patch

import pytest

from contracts.ProvenanceRegistry import (
    ProvenanceRegistry,
    VERIFICATION_THRESHOLD,
    REPUTATION_PENALTY_PER_UPHELD_DISPUTE,
)


@pytest.fixture
def contract():
    """Fresh contract instance for each test."""
    return ProvenanceRegistry()


@pytest.fixture
def artist_wallet():
    return "0xArtistWallet"


@pytest.fixture
def attacker_wallet():
    return "0xAttackerWallet"


# ─── register_artist ───────────────────────────────────────────────────────


def test_register_artist_verified_when_score_above_threshold(contract, artist_wallet):
    with patch("contracts.ProvenanceRegistry._fetch_sources", return_value=[
        "Skee Mask — electronic music producer, Berlin, releases on Ilian Tape.",
        "Skee Mask — discography, releases, bio.",
        "Skee Mask — DJ sets, events.",
    ]), patch(
        "contracts.ProvenanceRegistry._llm_score_identity", return_value=85
    ):
        with patch("contracts.ProvenanceRegistry.msg") as msg, \
             patch("contracts.ProvenanceRegistry.block") as block:
            msg.sender = artist_wallet
            block.timestamp = 1000
            result = contract.register_artist(
                did="did:web:skee.mask",
                name="Skee Mask",
                evidence_urls=["url1", "url2", "url3"],
            )
    assert "Verified" in result
    assert "85" in result
    assert artist_wallet in contract.artists
    assert contract.artists[artist_wallet].score == 85
    assert contract.artists[artist_wallet].verified_at == 1000


def test_register_artist_not_verified_when_score_below_threshold(contract, artist_wallet):
    with patch("contracts.ProvenanceRegistry._fetch_sources", return_value=[
        "Random blog post",
        "Unrelated content",
    ]), patch(
        "contracts.ProvenanceRegistry._llm_score_identity", return_value=42
    ):
        with patch("contracts.ProvenanceRegistry.msg") as msg:
            msg.sender = artist_wallet
            result = contract.register_artist(
                did="did:web:fake",
                name="Fake Artist",
                evidence_urls=["url1", "url2"],
            )
    assert "Not verified" in result
    assert "42" in result
    assert artist_wallet not in contract.artists
    # But the count and score are still updated
    assert contract.identity_count[artist_wallet] == 1
    assert contract.identity_score[artist_wallet] == 42


def test_register_artist_evidence_capped_at_five_urls(contract, artist_wallet):
    """Even if 100 URLs are passed, only the first 5 should be fetched."""
    with patch("contracts.ProvenanceRegistry._fetch_sources", return_value=[
        "src1", "src2", "src3", "src4", "src5"
    ]) as fetch_mock, patch(
        "contracts.ProvenanceRegistry._llm_score_identity", return_value=80
    ):
        with patch("contracts.ProvenanceRegistry.msg") as msg:
            msg.sender = artist_wallet
            urls = [f"https://example.com/{i}" for i in range(20)]
            contract.register_artist(
                did="did:web:someone",
                name="Someone",
                evidence_urls=urls,
            )
    # Only 5 sources passed through to the leader function
    assert len(fetch_mock.call_args[0][0]) == 5


# ─── anchor_release ────────────────────────────────────────────────────────


def test_anchor_release_succeeds_for_verified_artist(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x01" * 32
    with patch("contracts.ProvenanceRegistry.msg") as msg, \
         patch("contracts.ProvenanceRegistry.block") as block:
        msg.sender = artist_wallet
        block.timestamp = 2000
        result = contract.anchor_release(
            audio_hash=audio_hash,
            title="Test EP",
            contributors=[artist_wallet],
            release_date=1234567890,
        )
    assert "Anchored" in result
    assert contract.releases[audio_hash].title == "Test EP"
    assert audio_hash in contract.artist_releases[artist_wallet]


def test_anchor_release_rejects_unverified_wallet(contract, attacker_wallet):
    audio_hash = b"\x02" * 32
    with patch("contracts.ProvenanceRegistry.msg") as msg:
        msg.sender = attacker_wallet
        result = contract.anchor_release(
            audio_hash=audio_hash,
            title="Fake Release",
            contributors=[attacker_wallet],
            release_date=1234567890,
        )
    assert result == "Not a verified artist"
    assert audio_hash not in contract.releases


def test_anchor_release_rejects_duplicate_hash(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x03" * 32
    with patch("contracts.ProvenanceRegistry.msg") as msg, \
         patch("contracts.ProvenanceRegistry.block") as block:
        msg.sender = artist_wallet
        block.timestamp = 2000
        contract.anchor_release(
            audio_hash=audio_hash,
            title="First",
            contributors=[artist_wallet],
            release_date=1000,
        )
        result = contract.anchor_release(
            audio_hash=audio_hash,
            title="Second",
            contributors=[artist_wallet],
            release_date=2000,
        )
    assert "already anchored" in result


# ─── dispute ───────────────────────────────────────────────────────────────


def test_dispute_upheld_marks_release_contested_and_penalizes_artist(
    contract, artist_wallet, attacker_wallet
):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x04" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch("contracts.ProvenanceRegistry._llm_judge_dispute", return_value=85), \
         patch("contracts.ProvenanceRegistry.msg") as msg, \
         patch("contracts.ProvenanceRegistry.block") as block:
        msg.sender = attacker_wallet
        block.timestamp = 5000
        result = contract.dispute(
            audio_hash=audio_hash,
            claim="This is actually an AI-generated track",
            evidence_url="https://example.com/ai-evidence",
        )
    assert "upheld" in result
    assert contract.releases[audio_hash].contested is True
    # Reputation penalized
    assert contract.identity_score[artist_wallet] == 80 - REPUTATION_PENALTY_PER_UPHELD_DISPUTE
    # Verified status stripped
    assert contract.artists[artist_wallet].verified_at == 0
    # Dispute stored
    assert contract.disputes[audio_hash].resolution == "Upheld"


def test_dispute_dismissed_leaves_release_clean(contract, artist_wallet, attacker_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x05" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch("contracts.ProvenanceRegistry._llm_judge_dispute", return_value=20), \
         patch("contracts.ProvenanceRegistry.msg") as msg, \
         patch("contracts.ProvenanceRegistry.block") as block:
        msg.sender = attacker_wallet
        block.timestamp = 5000
        result = contract.dispute(
            audio_hash=audio_hash,
            claim="This is fake, trust me bro",
            evidence_url="https://example.com/no-evidence",
        )
    assert "dismissed" in result
    assert contract.releases[audio_hash].contested is False
    # Reputation NOT penalized
    assert contract.identity_score[artist_wallet] == 80


def test_dispute_on_own_release_rejected(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x06" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)

    with patch("contracts.ProvenanceRegistry.msg") as msg:
        msg.sender = artist_wallet
        result = contract.dispute(
            audio_hash=audio_hash,
            claim="I want to dispute my own track",
            evidence_url="https://example.com",
        )
    assert "Cannot dispute your own release" in result


def test_dispute_on_unknown_release_rejected(contract, attacker_wallet):
    with patch("contracts.ProvenanceRegistry.msg") as msg:
        msg.sender = attacker_wallet
        result = contract.dispute(
            audio_hash=b"\x07" * 32,
            claim="This release doesn't exist",
            evidence_url="https://example.com",
        )
    assert "Release not found" in result


# ─── is_verified_human ─────────────────────────────────────────────────────


def test_is_verified_human_true_for_clean_release(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x08" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)
    assert contract.is_verified_human(audio_hash) is True


def test_is_verified_human_false_for_unknown_hash(contract):
    assert contract.is_verified_human(b"\x09" * 32) is False


def test_is_verified_human_false_for_contested_release(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x0a" * 32
    release = _make_release(artist_wallet, audio_hash)
    release.contested = True
    contract.releases[audio_hash] = release
    assert contract.is_verified_human(audio_hash) is False


def test_is_verified_human_false_for_low_score_artist(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=60)
    audio_hash = b"\x0b" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash)
    assert contract.is_verified_human(audio_hash) is False


# ─── get_* view methods ────────────────────────────────────────────────────


def test_get_artist_unregistered_returns_not_verified(contract, artist_wallet):
    result = contract.get_artist(artist_wallet)
    assert result == {"verified": False}


def test_get_artist_verified(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=85)
    result = contract.get_artist(artist_wallet)
    assert result["verified"] is True
    assert result["name"] == "Skee Mask"
    assert result["score"] == 85


def test_get_release_returns_metadata(contract, artist_wallet):
    contract.artists[artist_wallet] = _make_artist(artist_wallet, score=80)
    audio_hash = b"\x0c" * 32
    contract.releases[audio_hash] = _make_release(artist_wallet, audio_hash, title="Compro")
    result = contract.get_release(audio_hash)
    assert result["found"] is True
    assert result["title"] == "Compro"
    assert result["contested"] is False


def test_get_release_unknown_returns_not_found(contract):
    result = contract.get_release(b"\x0d" * 32)
    assert result == {"found": False}


# ─── Helpers ───────────────────────────────────────────────────────────────


def _make_artist(wallet, *, score=80):
    from contracts.ProvenanceRegistry import Artist
    return Artist(
        wallet=wallet,
        did="did:web:test",
        name="Skee Mask",
        verified_at=1000,
        score=score,
    )


def _make_release(wallet, audio_hash, *, title="Test"):
    from contracts.ProvenanceRegistry import Release
    return Release(
        artist=wallet,
        title=title,
        audio_hash=audio_hash,
        contributors=[wallet],
        release_date=1234567890,
        anchored_at=2000,
        contested=False,
    )
