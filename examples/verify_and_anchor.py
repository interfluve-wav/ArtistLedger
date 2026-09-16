"""
End-to-end demo for OnChainProvenanceRegistry.

Flow:
  1. Connect to GenLayer testnet
  2. Deploy ProvenanceRegistry
  3. Register a real artist (Burial) with 3 evidence URLs
  4. Anchor a real release
  5. Query is_verified_human -> True
  6. File a dispute with bogus evidence
  7. Query is_verified_human -> still True (bogus dispute dismissed)

This demo shows the happy path. The dispute-uphold path is exercised in
tests/test_provenance.py.
"""

import os
import time

from genlayer import Address, Client

ARTIST_DID = "did:web:burial"
ARTIST_NAME = "Burial"
EVIDENCE_URLS = [
    "https://musicbrainz.org/artist/9ddce51c-2b75-4b3e-ac8c-1db09e7c89c6",
    "https://music.apple.com/us/artist/burial/468355684",
    "https://burial.bandcamp.com/",
]

AUDIO_HASH = bytes(range(32))  # demo bytes — not a real key material
RELEASE_TITLE = "Untrue"
RELEASE_DATE = int(time.mktime((2007, 11, 5, 0, 0, 0, 0, 0, 0)))


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
