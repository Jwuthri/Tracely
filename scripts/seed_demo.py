"""Seed the FULL Tracely demo — the whole product, not half of it.

ONE command populates every surface a visitor sees, in dependency order:

  1. Observe / Triage  — rich conversations (`seed_conversations.py`): every trace shape, plus the
     failures (tool error, hallucination, silent requested-but-not-executed tool, guardrail block)
  2. Triage            — cluster those failures into issues (`POST /api/clusters/rebuild`)
  3. Test / Ship       — promote failing traces into regression cases + run red→green CI gates
     (`seed_regression.py`) ← the DIFFERENTIATED half competitors don't have

Why this script exists: the README used to list steps 1 and 3 as two separate manual commands, so
it was trivial to run the first and forget the second — leaving Cases + Gates empty. An empty
Test/Ship half is exactly the "looks like a Langfuse clone" state where Tracely's moat is invisible
in its own running app. This guarantees the right half is always populated.

Idempotent: each phase is skipped when its data already exists (promote dedupes by input digest;
deterministic trace ids replace in place), so it is safe to run on every `docker compose up` — the
`seed-demo` compose profile runs exactly this.

    make demo
    # or:  docker compose --profile demo up -d --build --wait     (runs this inside the stack)
    # or:  TRACELY_API=http://localhost:8000 uv run python scripts/seed_demo.py [--force]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]
_EXAMPLES = _ROOT / "sdk" / "examples"

API = os.environ.get("TRACELY_API", "http://localhost:8000").rstrip("/")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")
FORCE = "--force" in sys.argv[1:]

# colors (no-op when not a tty)
_TTY = sys.stdout.isatty()
BOLD = "\033[1m" if _TTY else ""
DIM = "\033[2m" if _TTY else ""
OK = "\033[32m" if _TTY else ""
WARN = "\033[33m" if _TTY else ""
OFF = "\033[0m" if _TTY else ""


def _req(method: str, path: str, body: dict | None = None, timeout: float = 30.0):
    """Call the Tracely API. Returns (status_code, parsed_json | None)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def _run_example(script: str) -> int:
    """Run an sdk/examples script as a child, streaming its output, with our API/KEY in env."""
    env = {**os.environ, "TRACELY_API": API, "TRACELY_KEY": KEY}
    proc = subprocess.run([sys.executable, str(_EXAMPLES / script)], env=env, check=False)
    return proc.returncode


def _wait_reachable(attempts: int = 60) -> bool:
    for _ in range(attempts):
        status, _body = _req("GET", "/api/traces?limit=1", timeout=5.0)
        if status == 200:
            return True
        time.sleep(1.0)
    return False


def _has_traces() -> bool:
    _status, body = _req("GET", "/api/traces?limit=1")
    return bool(body)


def _promoted_cases() -> int:
    _status, body = _req("GET", "/api/cases")
    return sum(1 for c in (body or []) if c.get("status") == "PROMOTED")


def _counts() -> tuple[int, int, int]:
    _s1, traces = _req("GET", "/api/traces?limit=500")
    _s2, clusters = _req("GET", "/api/clusters")
    _s3, gates = _req("GET", "/api/gates")
    return len(traces or []), len(clusters or []), len(gates or [])


def main() -> None:
    print(f"{BOLD}Seeding the full Tracely demo → {API}{OFF}")
    if not _wait_reachable():
        print(
            f"{WARN}backend not reachable at {API}{OFF}\n"
            f"  start it first (docker compose up / make backend), or set TRACELY_API to the right port.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── 1. Observe / Triage — rich conversations + the raw failures ────────────────
    print(f"\n{BOLD}1/3 conversations{OFF} (traces, every shape + failures)")
    if _has_traces() and not FORCE:
        print(f"  {DIM}↷ traces already present — skipping (pass --force to add more){OFF}")
    elif _run_example("seed_conversations.py") != 0:
        print(f"  {WARN}seed_conversations.py failed — continuing{OFF}", file=sys.stderr)

    # ── 2. Triage — cluster the failures into issues ───────────────────────────────
    print(f"\n{BOLD}2/3 failure clusters{OFF}")
    status, body = _req("POST", "/api/clusters/rebuild")
    if status == 200:
        print(f"  rebuilding in the background (the worker groups failures into issues)…")
        time.sleep(3.0)  # let the task pick up; clusters appear once it finishes
    elif status == 400:
        detail = (body or {}).get("detail", "missing LLM/embedding keys")
        print(f"  {DIM}↷ skipped — {detail}{OFF}")
    else:
        print(f"  {WARN}cluster rebuild returned {status} — continuing{OFF}", file=sys.stderr)

    # ── 3. Test / Ship — promote failures → regression cases + red→green CI gates ──
    print(f"\n{BOLD}3/3 regression cases + CI gates{OFF} (the differentiated half)")
    if _promoted_cases() and not FORCE:
        print(f"  {DIM}↷ promoted cases already present — skipping (pass --force to add gate runs){OFF}")
    elif _run_example("seed_regression.py") != 0:
        print(f"  {WARN}seed_regression.py failed — continuing{OFF}", file=sys.stderr)

    # ── summary ────────────────────────────────────────────────────────────────────
    traces, clusters, gates = _counts()
    cases = _promoted_cases()
    print(
        f"\n{OK}{BOLD}demo ready{OFF} — "
        f"{traces} traces · {clusters} clusters · {cases} promoted cases · {gates} gate runs"
    )
    print(f"  open the app → Cases and Gates are populated (not just Traces + Clusters).")
    if not cases:
        print(
            f"  {WARN}note: 0 promoted cases — the Test/Ship half is still empty. "
            f"Check that the worker is running and re-run with --force.{OFF}"
        )
    print(f"  {DIM}next: re-break the agent and watch the gate block it → see DEMO.md{OFF}")


if __name__ == "__main__":
    main()
