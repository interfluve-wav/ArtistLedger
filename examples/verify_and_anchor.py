"""
End-to-end demo for OnChainProvenanceRegistry.

Flow:
  1. Connect to GenLayer testnet
  2. Deploy ProvenanceRegistry
  3. Register a real artist (Skee Mask) with 3 evidence URLs
  4. Anchor a real release
  5. Query is_verified_human -> True
  6. File a dispute with bogus evidence
  7. Query is_verified_human -> still True (bogus dispute dismissed)

This demo shows the happy path. The dispute-uphold path is exercised in
tests/test_provenance.py.
"""

import os
import time
from genlayer import Client, Address

ARTIST_DID = "did:web:skee.mask"
ARTIST_NAME = "Skee Mask"
EVIDENCE_URLS = [
    "https://musicbrainz.org/artist/Skee+Mask",
    "https://ilian-tape.bandcamp.com/",
    "https://www.residentadvisor.net/dj/skeemask",
]

AUDIO_HASH = bytes.fromhex(
    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
)
RELEASE_TITLE = "Compro"
RELEASE_DATE = int(time.mktime((2024, 6, 14, 0, 0, 0, 0, 0, 0)))


def main() -> None:
    client = Client(network="testnet")
    wallet = Address(os.environ["DEPLOYER_PRIVATE_KEY"])
    client.connect(wallet=wallet)

    print(f"Deploying ProvenanceRegistry from {wallet}...")
    contract = client.deploy(
        contract_path="contracts/ProvenanceRegistry.py"
    )
    print(f"Deployed at: {contract.address}")

    print(f"\nRegistering artist '{ARTIST_NAME}' with {len(EVIDENCE_URLS)} sources...")
    result = contract.call(
        "register_artist",
        ARTIST_DID,
        ARTIST_NAME,
        EVIDENCE_URLS,
    )
    print(f"  Result: {result}")

    print(f"\nAnchoring release '{RELEASE_TITLE}'...")
    anchor_result = contract.call(
        "anchor_release",
        AUDIO_HASH,
        RELEASE_TITLE,
        [wallet],
        RELEASE_DATE,
    )
    print(f"  Result: {anchor_result}")

    print("\nQuerying is_verified_human...")
    is_human = contract.view("is_verified_human", AUDIO_HASH)
    print(f"  is_verified_human: {is_human}")

    print("\nFiling a bogus dispute (should be dismissed)...")
    bogus = contract.call(
        "dispute",
        AUDIO_HASH,
        "This is actually an AI-generated track by Suno",
        "https://example.com/nothing-here",
    )
    print(f"  Dispute result: {bogus}")

    print("\nRe-querying is_verified_human...")
    is_human_after = contract.view("is_verified_human", AUDIO_HASH)
    print(f"  is_verified_human: {is_human_after}")

    assert is_human is True, "Expected the real release to be verified"
    assert is_human_after is True, (
        "Bogus dispute should have been dismissed; release should remain verified"
    )
    print("\nAll assertions passed.")


if __name__ == "__main__":
    main()
