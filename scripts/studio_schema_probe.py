#!/usr/bin/env python3
"""Probe GenLayer Studio's GenVM schema check for a contract file.

Reproduces what the Studio editor does on paste: hex-encode the contract
source, POST it to the `gen_getContractSchemaForCode` JSON-RPC method,
and print the parsed schema or the GenVM error.

Verified 2026-09 against https://studio.genlayer.com/api/rpc (GenVM v0.2.16).
Stdlib only.

Usage:
    python3 studio_schema_probe.py path/to/Contract.py [--rpc URL]

Exit codes: 0 = schema OK, 1 = GenVM error, 2 = transport/usage error.
"""
import json
import re
import sys
import urllib.request

DEFAULT_RPC = "https://studio.genlayer.com/api/rpc"


def probe(path: str, rpc: str = DEFAULT_RPC) -> int:
    code = open(path, "rb").read()

    # GenVM's text parser requires the source to start with #, //, or --
    # or it throws invalid_contract absent_runner_comment.
    head = code[:4].decode("utf-8", errors="replace")
    if code[:1] == b"\xef" or not (
        head.startswith("#") or head.startswith("//") or head.startswith("--")
    ):
        print(f"WARN: file starts with {head!r} — GenVM needs the first "
              f"characters to be '#' (or '//' / '--'), no BOM/blank lines.")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "gen_getContractSchemaForCode",
        "params": {"contract_code_hex": code.hex()},
    }
    req = urllib.request.Request(
        rpc,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            # Studio's RPC requires a browser UA; plain urllib gets 403
            # (verified 2026-09 against studio.genlayer.com/api/rpc).
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except Exception as e:
        print(f"TRANSPORT ERROR: {e}")
        return 2

    if "result" in data:
        r = data["result"]
        if isinstance(r, dict):
            # methods entries observed as plain strings (method names)
            methods = [m if isinstance(m, str) else m.get("name")
                       for m in r.get("methods", [])]
            print(f"SCHEMA OK — ctor: {bool(r.get('ctor'))}, "
                  f"methods ({len(methods)}): {methods}")
        else:
            print(f"SCHEMA OK (raw): {str(r)[:200]}")
        return 0

    msg = data.get("error", {}).get("message", "unknown error")
    # The GenVM result JSON is embedded in the error message; pull out
    # the concise VM_ERROR line if present.
    m = re.search(r'"message":\s*"([^"]+)"\s*\}', msg)
    print(f"GENVM ERROR: {m.group(1) if m else msg[:500]}")
    return 1


if __name__ == "__main__":
    args = sys.argv[1:]
    rpc = DEFAULT_RPC
    if "--rpc" in args:
        i = args.index("--rpc")
        rpc = args[i + 1]
        del args[i:i + 2]
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(probe(args[0], rpc))
