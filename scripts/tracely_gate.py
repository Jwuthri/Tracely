"""Deprecated shim — the gate now lives in the SDK as the `tracely` CLI.

    pip install ./sdk         # or: pip install tracely-sdk
    tracely gate <agent>      # triggers the gate, exits 0/1, posts the PR check in CI

This file forwards to that CLI so existing `python scripts/tracely_gate.py <agent>` callers
keep working. New usage should call `tracely gate` directly (see .github/actions/tracely-gate).
"""

from __future__ import annotations

import os
import sys

try:
    from tracely_sdk.cli import main
except ImportError:
    sys.exit("install the Tracely SDK first: `pip install ./sdk` (provides the `tracely` CLI)")

if __name__ == "__main__":
    agent = os.environ.get("TRACELY_AGENT") or (sys.argv[1] if len(sys.argv) > 1 else "")
    argv = ["gate"] + (["--agent", agent] if agent else [])
    sys.exit(main(argv))
