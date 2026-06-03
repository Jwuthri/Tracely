"""Tracely CI gate — run an agent's regression suite against this CI run's traces.

Exits non-zero if the gate FAILs. Run it in CI AFTER your agent has emitted traces
to Tracely tagged tracely.env=ci.

  TRACELY_API=... TRACELY_KEY=... TRACELY_AGENT=planner python scripts/tracely_gate.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")
AGENT = os.environ.get("TRACELY_AGENT") or (sys.argv[1] if len(sys.argv) > 1 else "")
ENV = os.environ.get("TRACELY_GATE_ENV", "ci")
GIT = os.environ.get("GITHUB_SHA") or os.environ.get("GIT_REF", "")
PR = os.environ.get("PR_NUMBER") or os.environ.get("GITHUB_PR_NUMBER", "")

ICON = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}


def main() -> int:
    if not AGENT:
        print("set TRACELY_AGENT (or pass the agent slug as the first argument)")
        return 2

    body = json.dumps(
        {"agent": AGENT, "env": ENV, "git_ref": GIT, "pr_number": int(PR) if PR.isdigit() else None}
    ).encode()
    req = urllib.request.Request(
        f"{API}/api/gate",
        data=body,
        headers={"Authorization": f"Bearer {KEY}", "content-type": "application/json"},
    )
    try:
        data = json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        print("gate error:", e.code, e.read().decode())
        return 2

    print(f"\nTracely gate · agent={data['agent']} · env={data['env']} · {GIT[:8]}")
    print(f"  {data['passed']} passed · {data['failed']} failed · {data['skipped']} skipped\n")
    for c in data.get("cases", []):
        d = c.get("detail") or {}
        extra = ""
        if c["verdict"] == "FAIL" and d.get("erroring_steps"):
            extra = "  errors: " + ", ".join(d["erroring_steps"])
        elif c["verdict"] == "SKIP":
            extra = "  (" + (d.get("reason") or "not exercised") + ")"
        print(f"  {ICON.get(c['verdict'], '?')} {c['verdict']:<4} {c['title']}{extra}")
    print(f"\n  Result: {data['status']}\n")
    return 0 if data["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
