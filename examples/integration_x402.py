"""
x402 + ProvenanceRegistry integration pseudocode.

Shows how a streaming platform, sync licensor, or x402 payment flow can
use ProvenanceRegistry to gate transactions on provenance.

This file is not a runnable example — it documents the integration
pattern in plain Python so the contract authors can see how their
work is consumed.

See: https://portal.genlayer.foundation/genesis/compass
      "x402 has no formal dispute mechanism"
"""

from dataclasses import dataclass


@dataclass
class Track:
    audio_hash: bytes
    claimed_artist: str
    seller_wallet: str
    price_usdc: int


@dataclass
class Payment:
    def execute(self, to: str, amount: int) -> bool:
        # Real x402 flow here
        ...


class ProvenanceRegistry:
    def is_verified_human(self, audio_hash: bytes) -> bool: ...
    def get_release(self, audio_hash: bytes) -> dict: ...
    def get_dispute(self, audio_hash: bytes) -> dict: ...


# ─── Errors ────────────────────────────────────────────────────────────────


class UnverifiedProvenanceError(Exception):
    """The track has not been verified as human-made by ProvenanceRegistry."""
    pass


class ContestedReleaseError(Exception):
    """The track has an upheld dispute on ProvenanceRegistry."""
    pass


class ArtistMismatchError(Exception):
    """The claimed artist does not match the ProvenanceRegistry record."""
    pass


# ─── The pattern ──────────────────────────────────────────────────────────


def purchase_track(
    track: Track, payment: Payment, provenance: ProvenanceRegistry
) -> bool:
    """
    Gate a track purchase on provenance verification.

    Three checks, in order of severity:
      1. Has the track been verified as human-made?
      2. Is there an active dispute against the release?
      3. Does the claimed artist match the onchain record?

    If any check fails, the payment is rejected with a specific error.
    A real production flow would also log the rejection reason for
    audit / dispute evidence.
    """
    # Check 1: is the track verified human-made at all?
    if not provenance.is_verified_human(track.audio_hash):
        raise UnverifiedProvenanceError(
            f"Track {track.audio_hash.hex()} is not verified as human-made"
        )

    # Check 2: has the release been disputed? (We already know the
    # release is verified above, but a verified release can be
    # later disputed; this is the asymmetric burden design.)
    dispute = provenance.get_dispute(track.audio_hash)
    if dispute.get("found") and dispute.get("resolution") == "Upheld":
        raise ContestedReleaseError(
            f"Track {track.audio_hash.hex()} has an upheld dispute: "
            f"{dispute.get('claim')}"
        )

    # Check 3: does the claimed artist match the onchain record?
    release = provenance.get_release(track.audio_hash)
    if release.get("artist") != track.seller_wallet:
        raise ArtistMismatchError(
            f"Track claims artist '{track.claimed_artist}' but onchain "
            f"record shows '{release.get('artist')}'"
        )

    # All checks passed — execute the payment
    return payment.execute(track.seller_wallet, track.price_usdc)


# ─── How a streaming playlist would use this ──────────────────────────────


def add_to_human_made_playlist(
    track: Track, provenance: ProvenanceRegistry
) -> bool:
    """
    A streaming platform's "human-made" playlist uses the same
    is_verified_human check, but does not need to inspect the
    dispute or artist match — those are surfaced separately.
    """
    return provenance.is_verified_human(track.audio_hash)


# ─── How Internet Court would call this ──────────────────────────────────


class InternetCourtContract:
    """
    Pseudocode for how Internet Court's verification & disputes layer
    would call ProvenanceRegistry.

    When a dispute is filed in an Internet Court contract about a
    delivered music asset, the court contract can ask:
      1. Is the deliverable's audio hash registered?
      2. Is the claimed artist onchain the same as the deliverer's
         claimed identity?
      3. Is there a parallel dispute on ProvenanceRegistry?
    """

    def adjudicate_music_delivery_dispute(
        self,
        audio_hash: bytes,
        deliverer_wallet: str,
        deliverer_claimed_artist: str,
        evidence_url: str,
    ) -> str:
        # The Internet Court contract would have a reference to a
        # ProvenanceRegistry instance (set at deploy time)
        provenance = self.provenance_registry  # type: ignore

        if not provenance.is_verified_human(audio_hash):
            return "REJECTED: audio not verified as human-made"

        release = provenance.get_release(audio_hash)
        if release.get("artist") != deliverer_wallet:
            return "REJECTED: deliverer wallet does not match onchain artist"

        if deliverer_claimed_artist != release.get("title"):
            # Could check claimed-artist name against the artist record
            return "REJECTED: deliverer claimed name does not match"

        # If all provenance checks pass, the Internet Court contract
        # continues with its own LLM-based judgment of the evidence
        return "PROVENANCE_OK: continuing to LLM adjudication of evidence"
