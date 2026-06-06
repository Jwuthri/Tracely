"""Seed the regression → CI-gate demo (the Test → Ship half of Tracely).

Tells a real red→green CI story end-to-end:
  1. a failing production trace (agent → llm → get_weather ERROR) is captured
  2. it's PROMOTED into a regression case (fail-to-pass validated: the source must FAIL it)
  3. a CI gate runs while the bug is still present  -> FAIL (the gate catches the regression)
  4. a CI gate runs after the fix (get_weather succeeds) -> PASS (the fix clears the gate)
  5. the case is replayed against the fixed trace -> PASS (recorded in the case's history)

Populates the otherwise-empty Regression cases + CI gates views.

    # inside the stack:
    docker compose exec backend python sdk/examples/seed_regression.py
    # or against a running API:
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/seed_regression.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")
AGENT = os.environ.get("TRACELY_AGENT", "planner")
HERE = os.path.dirname(os.path.abspath(__file__))
SENDER = os.path.normpath(os.path.join(HERE, "..", "..", "scripts", "send_test_trace.py"))


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def send_trace(**env_overrides: str) -> str:
    """Run the OTLP sender (deterministic trace ids) and return the trace id it printed."""
    env = {**os.environ, "TRACELY_API": API, "TRACELY_KEY": KEY,
           **{k: str(v) for k, v in env_overrides.items()}}
    out = subprocess.run([sys.executable, SENDER], env=env, capture_output=True, text=True, check=True).stdout
    m = re.search(r"trace_id \(hex\): ([0-9a-f]+)", out)
    if not m:
        raise RuntimeError(f"could not parse trace id from sender output:\n{out}")
    return m.group(1)


def wait_for(trace_id: str, timeout_s: int = 40) -> None:
    """Block until the async pipeline (blob → queue → worker → ClickHouse) has ingested the trace."""
    for _ in range(timeout_s * 2):
        if _req("GET", f"/api/traces/{trace_id}").get("spans"):
            return
        time.sleep(0.5)
    raise TimeoutError(f"trace {trace_id} was never ingested")


def main() -> None:
    print("1) production incident — failing weather run (get_weather errors)")
    fail_prod = send_trace()  # default variant = failing, env=prod
    wait_for(fail_prod)
    print(f"   trace {fail_prod[:16]}…")

    print("2) promote → regression case")
    case = _req("POST", f"/api/traces/{fail_prod}/promote")
    print(f"   case {case['id'][:8]}  status={case['status']}  fail_to_pass_validated={case['fail_to_pass_validated']}")

    print("3) CI gate on the PR that still has the bug → expect FAIL")
    fail_ci = send_trace(ENV="ci")  # the same failing run, tagged env=ci (a CI candidate)
    wait_for(fail_ci)
    g1 = _req("POST", "/api/gate", {"agent": AGENT, "env": "ci", "git_ref": "feat/weather-fix", "pr_number": 41})
    print(f"   gate {g1['id'][:8]}  {g1['status']}  (passed={g1['passed']} failed={g1['failed']} skipped={g1['skipped']})")

    print("4) CI gate after the fix (get_weather succeeds) → expect PASS")
    fixed_ci = send_trace(ENV="ci", FIXED="1"); wait_for(fixed_ci)
    g2 = _req("POST", "/api/gate", {"agent": AGENT, "env": "ci", "git_ref": "feat/weather-fix", "pr_number": 41})
    print(f"   gate {g2['id'][:8]}  {g2['status']}  (passed={g2['passed']} failed={g2['failed']} skipped={g2['skipped']})")

    print("5) replay the case against the fixed trace → expect PASS")
    r = _req("POST", f"/api/cases/{case['id']}/replay", {"candidate_trace_id": fixed_ci})
    print(f"   replay verdict={r['verdict']}")

    print("\ndone — open Regression cases + CI gates in the UI (red gate, then green).")


if __name__ == "__main__":
    main()
