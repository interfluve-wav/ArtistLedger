#!/usr/bin/env python3
"""
register_artist_smoke.py — end-to-end smoke test for register_artist.

Pipeline:
  1. Run find_artist.find_artist() to gather public-source URLs for a real artist.
  2. Build a register_artist call with the (did, name, audio_hash,
     source_urls, wallet, verification_source_1/2, ...).
  3. Print the call so it can be inspected before signing.
  4. Submit via genlayer write (requires a funded account on the network).
  5. Capture the receipt and report the consensus outcome
     (ACCEPTED / UNDETERMINED / REJECTED).

Usage:
    # Dry-run (no GEN needed): prints the full call, does not submit
    .venv/bin/python examples/register_artist_smoke.py \
        --name "Burial" --seed "https://www.discogs.com/artist/62418" \
        --dry-run

    # Live (requires funded deployer on studionet)
    .venv/bin/python examples/register_artist_smoke.py \
        --name "Burial" --seed "https://www.discogs.com/artist/62418" \
        --network studionet --contract 0x4Da983... --submit
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import find_artist as _fa_module  # noqa: E402

DEFAULT_CONTRACT = os.environ.get(
    "ARTISTLEDGER_CONTRACT", "0x4Da983553c0aafc16fD1Be26AcE5c0C2308EE760"
)
DEFAULT_AUDIO_HASH = "0x" + "11" * 32
DEFAULT_DEPLOYER = os.environ.get(
    "ARTISTLEDGER_DEPLOYER", "0xd3b809526bbd29f699b046e678190a777fd054a9"
)


def build_call(name: str, artist_data: dict, audio_hash: str, deployer: str) -> dict:
    sources = {}
    if artist_data.get("apple_music_url"):
        sources["apple_music"] = artist_data["apple_music_url"]
    if artist_data.get("musicbrainz_id"):
        sources["musicbrainz"] = (
            f"https://musicbrainz.org/artist/{artist_data['musicbrainz_id']}"
        )

    if not artist_data.get("apple_music_artist_id") and not artist_data.get("musicbrainz_id"):
        raise SystemExit(
            f"find_artist returned no tier-1 source for {name!r}. "
            f"Cannot build a register_artist call that will pass the new tier-1 floor."
        )

    src1 = "apple_music" if artist_data.get("apple_music_artist_id") else "musicbrainz"
    h1 = artist_data.get("apple_music_artist_id") or artist_data.get("musicbrainz_id")
    src2 = "musicbrainz" if src1 == "apple_music" and artist_data.get("musicbrainz_id") else ""
    h2 = artist_data.get("musicbrainz_id") if src2 else ""

    return {
        "did": f"did:musicbrainz:artist:{artist_data.get('musicbrainz_id', name.lower())}",
        "name": name,
        "audio_hash": audio_hash,
        "source_urls": sources,
        "wallet": deployer,
        "verification_source_1": src1,
        "verification_handle_1": h1 or "",
        "verification_source_2": src2,
        "verification_handle_2": h2 or "",
        "require_two_source": True,
    }


def call_genlayer(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["genlayer", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr


def submit(args_dict: dict, contract: str, network: str) -> str:
    rc, out, err = call_genlayer(
        [
            "--network", network,
            "write", contract, "register_artist",
            "--args",
            args_dict["did"],
            args_dict["name"],
            f"b#{args_dict['audio_hash'][2:]}",
            json.dumps(args_dict["source_urls"]),
            args_dict["wallet"],
            args_dict["verification_source_1"],
            args_dict["verification_handle_1"],
            args_dict["verification_source_2"],
            args_dict["verification_handle_2"],
            str(args_dict["require_two_source"]).lower(),
        ]
    )
    if rc != 0:
        print(f"genlayer write FAILED (exit {rc}):", file=sys.stderr)
        print(err, file=sys.stderr)
        raise SystemExit(rc)
    return out.strip().splitlines()[-1] if out.strip() else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="register_artist smoke test")
    ap.add_argument("--name", required=True, help="Artist name (e.g. 'Burial')")
    ap.add_argument(
        "--seed", action="append", required=True,
        help="Known artist URL. Pass multiple times for several seeds.",
    )
    ap.add_argument("--audio-hash", default=DEFAULT_AUDIO_HASH)
    ap.add_argument("--deployer", default=DEFAULT_DEPLOYER)
    ap.add_argument("--contract", default=DEFAULT_CONTRACT)
    ap.add_argument("--network", default="studionet")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the call, do not submit (no GEN needed).")
    ap.add_argument("--submit", action="store_true",
                    help="Actually submit via genlayer write (needs funded account).")
    args = ap.parse_args()

    print(f"=== find_artist for {args.name!r} ===", file=sys.stderr)
    data = _fa_module.find_artist(args.name, args.seed)
    if not data:
        print("find_artist returned nothing — aborting.", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2), file=sys.stderr)

    print(f"\n=== register_artist call ===", file=sys.stderr)
    call = build_call(args.name, data, args.audio_hash, args.deployer)
    print(json.dumps(call, indent=2), file=sys.stderr)

    if args.dry_run or not args.submit:
        print("\n(dry-run; not submitted)", file=sys.stderr)
        return 0

    print(f"\n=== submitting to {args.contract} on {args.network} ===", file=sys.stderr)
    tx = submit(call, args.contract, args.network)
    print(f"tx hash: {tx}", file=sys.stderr)

    print(f"\n=== receipt ===", file=sys.stderr)
    rc, out, err = call_genlayer(["--network", args.network, "receipt", tx])
    print(out, file=sys.stderr)
    if err:
        print(err, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
