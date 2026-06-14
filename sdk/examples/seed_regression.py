"""Seed the regression → CI-gate demo (the Test → Ship half of Tracely).

Built around a SILENT failure — the model asked for `get_weather` but the agent never executed it,
so it answered without the tool. That's an agent-LOGIC bug, which both gating paths can validate:

  1. the silent production trace is PROMOTED into a regression case (fail-to-pass validated: the
     source FAILs because it never called the required tool)
  2. a CI gate while the bug is still present (still no tool call) -> FAIL
  3. a CI gate after the fix (the agent now calls get_weather) -> PASS
  4. the case is replayed against the fixed trace -> PASS

Because the required tool is the *requested-but-not-executed* one, the hermetic replay path works
too — `tracely replay planner --entrypoint weather_agent:run` PASSes (run calls the tool) while
`...:run_broken` FAILs (it doesn't). The GitHub Action runs exactly that.

    docker compose exec backend python sdk/examples/seed_regression.py
    # or: TRACELY_API=http://localhost:8000 uv run python sdk/examples/seed_regression.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")
AGENT = os.environ.get("TRACELY_AGENT", "planner")
HERE = os.path.dirname(os.path.abspath(__file__))
SENDER = os.path.normpath(os.path.join(HERE, "..", "..", "scripts", "send_test_trace.py"))


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def send_trace(**env_overrides: str) -> str:
    """Run the OTLP sender (deterministic trace ids) and return the trace id it printed."""
    env = {
        **os.environ,
        "TRACELY_API": API,
        "TRACELY_KEY": KEY,
        **{k: str(v) for k, v in env_overrides.items()},
    }
    out = subprocess.run(
        [sys.executable, SENDER], env=env, capture_output=True, text=True, check=True
    ).stdout
    m = re.search(r"trace_id \(hex\): ([0-9a-f]+)", out)
    if not m:
        raise RuntimeError(f"could not parse trace id from sender output:\n{out}")
    return m.group(1)


def wait_for(trace_id: str, timeout_s: int = 120) -> None:
    """Block until the async pipeline (blob → queue → worker → ClickHouse) has ingested the trace.

    The single-process (`--pool=solo`) worker interleaves ingest with LLM-judge auto-eval, so under
    a burst of demo traces an ingest can queue behind several judge calls — hence the generous
    timeout. (In production the ingest and eval queues should be split / the worker scaled out.)"""
    for _ in range(timeout_s * 2):
        if _req("GET", f"/api/traces/{trace_id}").get("spans"):
            return
        time.sleep(0.5)
    raise TimeoutError(f"trace {trace_id} was never ingested")


def run_gate(git_ref: str, pr: int, env: str = "ci") -> dict:
    return _req("POST", "/api/gate", {"agent": AGENT, "env": env, "git_ref": git_ref, "pr_number": pr})


def send_and_wait(**env_overrides: str) -> str:
    """Emit a demo trace and block until it's ingested; returns the trace id."""
    tid = send_trace(**env_overrides)
    wait_for(tid)
    return tid


def gate_line(label: str, g: dict) -> None:
    print(
        f"   {label}: gate {g['id'][:8]}  {g['status']}  "
        f"(passed={g['passed']} failed={g['failed']} skipped={g['skipped']})"
    )
    for c in g.get("cases", []):
        d = c.get("detail") or {}
        why = ""
        if d.get("missing_tools"):
            why = f"missing {d['missing_tools']}"
        elif d.get("quality_pass") is False:
            why = f"answer quality {d.get('quality_score')}: {(d.get('quality_reason') or '')[:70]}"
        print(f"        • {c['verdict']:<4} {c['title'][:24]:24} {why}")


def main() -> None:
    print("══ Scenario A — STRUCTURAL bug (silent failure: model requests get_weather, never calls it) ══")
    print("1) production incident → ingest")
    fail_prod = send_trace(SILENT="1")  # silent variant, env=prod
    wait_for(fail_prod)
    print(f"   trace {fail_prod[:16]}…")

    print("2) promote → regression case (asserts the fix must actually call get_weather)")
    case = _req("POST", f"/api/traces/{fail_prod}/promote")
    req = (case.get("assertions") or {}).get("required_tools")
    print(f"   case {case['id'][:8]}  status={case['status']}  required_tools={req}  fail_to_pass={case['fail_to_pass_validated']}")

    print("3) CI gate while the bug is present (no tool call) → expect FAIL")
    send_and_wait(ENV="ci", SILENT="1")
    gate_line("still broken", run_gate("feat/weather-fix", 41))

    print("4) CI gate after the fix (agent now calls get_weather) → expect PASS")
    fixed_ci = send_trace(ENV="ci", FIXED="1")
    wait_for(fixed_ci)
    gate_line("fixed", run_gate("feat/weather-fix", 41))

    print("5) replay the case against the fixed trace → expect PASS")
    r = _req("POST", f"/api/cases/{case['id']}/replay", {"candidate_trace_id": fixed_ci})
    print(f"   replay verdict={r['verdict']}")

    print("\n══ Scenario B — QUALITY bug (HALLUCINATION: get_weather succeeds, but the answer is fabricated) ══")
    print("   A structural check PASSES this (the tool ran!). Only the judge-in-the-gate catches it.")
    print("6) production incident — hallucinated answer → ingest")
    hall_prod = send_trace(HALLUCINATE="1", QUERY_IDX="1")
    wait_for(hall_prod)
    print(f"   trace {hall_prod[:16]}…")

    print("7) promote → regression case (captures the answer-QUALITY failure, not a tool failure)")
    qcase = _req("POST", f"/api/traces/{hall_prod}/promote")
    q = (qcase.get("assertions") or {}).get("quality")
    print(f"   case {qcase['id'][:8]}  status={qcase['status']}  quality={q}  fail_to_pass={qcase['fail_to_pass_validated']}")

    print("8) CI gate while the answer is STILL hallucinated → structural PASS, QUALITY FAIL → gate FAIL")
    send_and_wait(HALLUCINATE="1", QUERY_IDX="1", ENV="ci")
    gate_line("still hallucinating", run_gate("feat/answer-fix", 42))

    print("9) CI gate after the answer is fixed (faithful to the tool) → expect PASS")
    send_and_wait(FIXED="1", QUERY_IDX="1", ENV="ci")
    gate_line("answer fixed", run_gate("feat/answer-fix", 42))

    print("\n══ Safety — a gate that matched NO CI traces must NOT be a false green ══")
    gate_line("no coverage", run_gate("test-coverage", 43, env="staging"))

    print("\ndone — Regression cases + CI gates now show TWO red→green stories (structural + quality),")
    print("plus the NO_COVERAGE safety net. Hermetic replay also works:")
    print(f"   docker compose exec backend sh -c 'cd /app && PYTHONPATH=sdk/examples tracely replay {AGENT} --entrypoint weather_agent:run'        # PASS")
    print(f"   docker compose exec backend sh -c 'cd /app && PYTHONPATH=sdk/examples tracely replay {AGENT} --entrypoint weather_agent:run_broken' # FAIL")


if __name__ == "__main__":
    main()
