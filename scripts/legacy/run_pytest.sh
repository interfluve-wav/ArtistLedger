#!/bin/bash
# Run the pytest unit-test suite for ProvenanceRegistry
# Pre-conditions:
#   - python3.11+ venv at .venv
#   - pip install -e ".[dev]"  (or pip install pytest pytest-mock)
#   - genlayer runtime is required (py-genlayer or testnet deployer)
#     - on Mac: `genlayer up` then run inside that environment, OR
#     - run from a deployer container that has py-genlayer
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/pytest tests/test_provenance.py -v --no-header "$@"
