"""`tracely` CLI — the CI/CD gate.

Run an agent's PROMOTED regression suite against the traces this CI run emitted
(tagged tracely.env=ci) and turn the result into a real pull-request check:

    tracely gate --agent planner

Exits 0 on PASS, 1 on FAIL, 2 on error — so it blocks a merge on its own. Inside a
GitHub Actions run (or with --github) it also posts a commit status + a PR comment,
linking back to the gate in the Tracely UI. Stdlib only, so it installs with the SDK
and runs anywhere CI does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

MARKER = "<!-- tracely-gate -->"
STATUS_CONTEXT = "tracely/regression-gate"
ICON = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}
EMOJI = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}


# ── Tracely API ──────────────────────────────────────────────────────────────


def _get_json(url: str, key: str):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    return json.load(urllib.request.urlopen(req))


def _post_json(url: str, key: str, body: dict):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))


def trigger_gate(
    api: str, key: str, agent: str, env: str, git_ref: str, pr: int | None,
    candidates: dict[str, str] | None = None,
) -> dict:
    body: dict = {"agent": agent, "env": env, "git_ref": git_ref, "pr_number": pr}
    if candidates:
        body["candidates"] = candidates  # explicit case_id -> trace_id pairing from replay
    return _post_json(f"{api.rstrip('/')}/api/gate", key, body)


def case_reason(detail: dict) -> str:
    """A short, human reason for a non-PASS case from the gate's detail payload."""
    d = detail or {}
    bits: list[str] = []
    if d.get("missing_tools"):
        bits.append("missing tools: " + ", ".join(d["missing_tools"]))
    if d.get("run_errors"):  # run-outcome assertion: the agent itself failed
        bits.append("run failed: " + ", ".join(d["run_errors"]))
    elif d.get("allow_tool_errors") and d.get("tool_errors"):  # tolerated (the agent handled it)
        bits.append("tool errored (handled): " + ", ".join(d["tool_errors"]))
    elif d.get("erroring_steps"):
        bits.append("errors: " + ", ".join(d["erroring_steps"]))
    if not d.get("tools_ok", True) and not d.get("missing_tools"):
        bits.append(f"tool sequence mismatch (mode={d.get('match_mode', '')})")
    if d.get("reason"):  # SKIP carries a plain reason
        bits.append(str(d["reason"]))
    return "; ".join(bits)


# ── console + markdown rendering ─────────────────────────────────────────────


def render_console(data: dict, sha: str) -> None:
    print(f"\nTracely gate · agent={data.get('agent')} · env={data.get('env')} · {sha[:8]}")
    print(f"  {data['passed']} passed · {data['failed']} failed · {data['skipped']} skipped\n")
    for c in data.get("cases", []):
        reason = case_reason(c.get("detail") or {})
        extra = f"  ({reason})" if reason else ""
        print(f"  {ICON.get(c['verdict'], '?')} {c['verdict']:<4} {c['title']}{extra}")
    for w in data.get("warnings") or []:
        print(f"  ⚠️  {w}")
    print(f"\n  Result: {data['status']}\n")


def render_markdown(data: dict, web_url: str, sha: str) -> str:
    status = data["status"]
    head = "🔴" if status == "FAIL" else "🟢" if status == "PASS" else "⚪"
    sha_txt = f"`{sha[:7]}`" if sha else ""
    lines = [
        MARKER,
        f"### {head} Tracely regression gate — **{status}**",
        "",
        f"`{data.get('agent')}` · {data['passed']} passed · {data['failed']} failed · "
        f"{data['skipped']} skipped · env `{data.get('env')}` · {sha_txt}",
        "",
        "| | Case | Verdict | Detail |",
        "|---|---|---|---|",
    ]
    for c in data.get("cases", []):
        reason = case_reason(c.get("detail") or {}).replace("|", "\\|")
        lines.append(f"| {EMOJI.get(c['verdict'], '❔')} | {c['title']} | {c['verdict']} | {reason} |")
    lines.append("")
    warnings = data.get("warnings") or []
    if warnings:
        lines.append("**⚠️ Soft warnings** (non-blocking):")
        lines += [f"- {w}" for w in warnings]
        lines.append("")
    if status == "FAIL":
        lines.append(
            "> These regression tests were promoted from **real production failures**. "
            "A FAIL means this change reintroduces — or fails to fix — a known failure."
        )
        lines.append("")
    if web_url:
        lines.append(f"[View the full gate run →]({web_url.rstrip('/')}/gates/{data['id']})")
    return "\n".join(lines)


# ── GitHub ───────────────────────────────────────────────────────────────────


def gh_context() -> tuple[str, str, int | None]:
    """(repo, head_sha, pr_number) resolved from the GitHub Actions environment."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("GITHUB_SHA", "")
    pr: int | None = None
    ev_path = os.environ.get("GITHUB_EVENT_PATH")
    if ev_path and os.path.exists(ev_path):
        try:
            with open(ev_path) as f:
                ev = json.load(f)
            prinfo = ev.get("pull_request") or {}
            if prinfo.get("number"):
                pr = int(prinfo["number"])
            head = (prinfo.get("head") or {}).get("sha")
            if head:
                sha = head  # post to the PR head commit, not the merge commit
        except Exception:
            pass
    if pr is None:
        m = re.match(r"refs/pull/(\d+)/", os.environ.get("GITHUB_REF", ""))
        if m:
            pr = int(m.group(1))
    return repo, sha, pr


class GitHub:
    def __init__(self, token: str, dry_run: bool = False):
        self.token = token
        self.dry_run = dry_run
        self.base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    def _call(self, method: str, path: str, body: dict | None = None):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        if self.dry_run:
            print(f"[dry-run] {method} {url}")
            if body is not None:
                print(json.dumps(body, indent=2))
            return {"id": 0, "html_url": url}
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "content-type": "application/json",
        })
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r) if r.length != 0 else {}
        except urllib.error.HTTPError as e:
            print(f"github {method} {path} -> {e.code}: {e.read().decode()[:300]}")
            return None

    def commit_status(self, repo: str, sha: str, state: str, description: str, target_url: str):
        self._call("POST", f"/repos/{repo}/statuses/{sha}", {
            "state": state,  # success | failure | error | pending
            "context": STATUS_CONTEXT,
            "description": description[:140],
            **({"target_url": target_url} if target_url else {}),
        })

    def upsert_comment(self, repo: str, pr: int, body: str):
        # update our previous comment in place (keyed by the hidden marker) instead of spamming
        existing = [] if self.dry_run else (self._call("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100") or [])
        prior = next(
            (c for c in existing if isinstance(c, dict) and MARKER in (c.get("body") or "")), None
        )
        if prior:
            self._call("PATCH", f"/repos/{repo}/issues/comments/{prior['id']}", {"body": body})
        else:
            self._call("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})


def write_step_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(markdown + "\n")


# ── command ──────────────────────────────────────────────────────────────────


def post_pr_check(args: argparse.Namespace, data: dict, web_url: str, repo: str, sha: str, pr: int | None) -> None:
    """Post the gate result to GitHub (commit status + PR comment) when running in/for Actions."""
    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    want_github = args.github or (os.environ.get("GITHUB_ACTIONS") == "true" and token)
    if not want_github or args.no_github:
        return
    if not token:
        print("note: --github requested but no GITHUB_TOKEN; skipping PR check")
        return
    if not repo:
        print("note: not in a GitHub repo context (no GITHUB_REPOSITORY); skipping PR check")
        return
    gh = GitHub(token, dry_run=args.dry_run)
    state = {"PASS": "success", "FAIL": "failure"}.get(data["status"], "error")
    desc = f"{data['passed']} passed · {data['failed']} failed · {data['skipped']} skipped"
    target = f"{web_url.rstrip('/')}/gates/{data['id']}" if web_url else ""
    if sha:
        gh.commit_status(repo, sha, state, desc, target)
    if pr:
        gh.upsert_comment(repo, pr, render_markdown(data, web_url, sha))
    print(f"posted gate check to {repo}" + (f" PR #{pr}" if pr else "") + (" (dry-run)" if args.dry_run else ""))


def _conn(args: argparse.Namespace) -> tuple[str, str, str, str]:
    api = args.api or os.environ.get("TRACELY_API", "http://localhost:8000")
    key = args.key or os.environ.get("TRACELY_KEY", "tracely_dev_key")
    web_url = args.web_url or os.environ.get("TRACELY_WEB_URL", "")
    agent = args.agent or os.environ.get("TRACELY_AGENT", "")
    return api, key, web_url, agent


def cmd_gate(args: argparse.Namespace) -> int:
    api, key, web_url, agent = _conn(args)
    if not agent:
        print("error: --agent (or TRACELY_AGENT) is required")
        return 2

    repo, sha, pr = gh_context()
    sha = args.sha or sha
    if args.pr is not None:
        pr = args.pr
    git_ref = sha or os.environ.get("GIT_REF", "")

    try:
        data = trigger_gate(api, key, agent, args.env, git_ref, pr)
    except urllib.error.HTTPError as e:
        print(f"gate error: {e.code} {e.read().decode()[:300]}")
        return 2
    except urllib.error.URLError as e:
        print(f"gate error: cannot reach Tracely at {api}: {e.reason}")
        return 2

    render_console(data, sha)
    write_step_summary(render_markdown(data, web_url, sha))
    post_pr_check(args, data, web_url, repo, sha, pr)
    return 0 if data["status"] == "PASS" else 1


def _load_entrypoint(spec: str):
    """Import a 'module:function' entrypoint from the current working directory."""
    import importlib

    if ":" not in spec:
        raise SystemExit("--entrypoint must be 'module:function' (e.g. my_agent:run)")
    mod_name, fn_name = spec.split(":", 1)
    sys.path.insert(0, os.getcwd())
    return getattr(importlib.import_module(mod_name), fn_name)


def _wait_for_traces(api: str, key: str, trace_ids: list[str], timeout: int = 45) -> bool:
    """Poll until the emitted traces have been ingested into ClickHouse (or time out)."""
    import time

    deadline = time.time() + timeout
    pending = set(trace_ids)
    while pending and time.time() < deadline:
        for tid in list(pending):
            try:
                if _get_json(f"{api.rstrip('/')}/api/traces/{tid}", key).get("spans"):
                    pending.discard(tid)
            except Exception:
                pass
        if pending:
            time.sleep(2)
    if pending:
        print(f"warning: {len(pending)} replayed trace(s) not ingested in {timeout}s; gating anyway")
    return not pending


def cmd_replay(args: argparse.Namespace) -> int:
    api, key, web_url, agent = _conn(args)
    if not agent:
        print("error: --agent (or TRACELY_AGENT) is required")
        return 2
    if not args.entrypoint and not args.cmd:
        print("error: provide --entrypoint module:func  or  --cmd '...'")
        return 2

    try:
        suite = _get_json(f"{api.rstrip('/')}/api/gate/suite?agent={agent}", key)
    except urllib.error.HTTPError as e:
        print(f"replay error: {e.code} {e.read().decode()[:200]}")
        return 2
    cases = suite.get("cases", [])
    if not cases:
        print(f"no promoted cases for '{agent}' — nothing to replay (promote a failure first)")
        return 0
    print(f"replaying {len(cases)} case(s) for {agent} (env={args.env})\n")

    pairings: dict[str, str] = {}
    if args.entrypoint:
        func = _load_entrypoint(args.entrypoint)
        import tracely_sdk as t  # lazy: only the replay path needs the tracing stack

        t.init(endpoint=api, api_key=key, service_name=agent, env=args.env)
        for c in cases:
            bundle = None if args.live else c.get("fixtures")
            with t.fixtures(bundle), t.agent(agent) as span:  # hermetic unless --live
                t.set_io(span, input=c["input"])
                try:
                    out = func(c["input"])
                except Exception as exc:  # a crashing agent is itself a failing replay
                    t.error(span, f"agent raised: {exc}")
                    out = f"<error: {exc}>"
                t.set_io(span, output=out if isinstance(out, str) else json.dumps(out, default=str))
                tid = format(span.get_span_context().trace_id, "032x")
            n_fx = len((bundle or {}).get("tools") or {}) + len((bundle or {}).get("llm") or {})
            pairings[c["id"]] = tid
            tag = f"  [{n_fx} fixtures]" if n_fx else "  [live]"
            print(f"  · {c['title']}  ->  {tid[:12]}…{tag}")
        t.flush()
        _wait_for_traces(api, key, list(pairings.values()))
    else:
        import subprocess
        import time

        for c in cases:
            env = {**os.environ, "TRACELY_INPUT": c["input"], "TRACELY_API": api,
                   "TRACELY_KEY": key, "TRACELY_ENV": args.env}
            subprocess.run(args.cmd, shell=True, env=env, check=False)
            print(f"  · ran cmd for {c['title']}")
        time.sleep(8)  # external process emits its own trace; give ingestion a moment

    repo, sha, pr = gh_context()
    sha = args.sha or sha
    if args.pr is not None:
        pr = args.pr
    # explicit pairing for the entrypoint path; digest matching for the --cmd path
    data = trigger_gate(api, key, agent, args.env, sha or "", pr, candidates=pairings or None)

    render_console(data, sha)
    write_step_summary(render_markdown(data, web_url, sha))
    post_pr_check(args, data, web_url, repo, sha, pr)
    return 0 if data["status"] == "PASS" else 1


def _add_common_gate_flags(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--env", default=os.environ.get("TRACELY_GATE_ENV", "ci"))
    sp.add_argument("--api", help="Tracely API base (TRACELY_API)")
    sp.add_argument("--key", help="Tracely ingest key (TRACELY_KEY)")
    sp.add_argument("--web-url", help="Tracely web base for links (TRACELY_WEB_URL)")
    sp.add_argument("--pr", type=int, help="PR number (else inferred from the Actions event)")
    sp.add_argument("--sha", help="commit SHA (else inferred)")
    sp.add_argument("--github", action="store_true", help="post a commit status + PR comment")
    sp.add_argument("--no-github", action="store_true", help="never touch GitHub even inside Actions")
    sp.add_argument("--token", help="GitHub token (else GITHUB_TOKEN)")
    sp.add_argument("--dry-run", action="store_true", help="print the GitHub calls instead of sending")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tracely", description="Tracely CI/CD gate")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gate", help="gate a PR on pre-emitted ci traces (matched by input)")
    g.add_argument("agent", nargs="?", help="agent slug (or --agent / TRACELY_AGENT)")
    g.add_argument("--agent", dest="agent_opt", help="agent slug")
    _add_common_gate_flags(g)

    r = sub.add_parser("replay", help="re-run the agent on each promoted case, then gate the PR")
    r.add_argument("agent", nargs="?", help="agent slug (or --agent / TRACELY_AGENT)")
    r.add_argument("--agent", dest="agent_opt", help="agent slug")
    r.add_argument("--entrypoint", help="Python agent as 'module:function'; called with each case input")
    r.add_argument("--cmd", help="shell command to run per case (gets TRACELY_INPUT); emits its own trace")
    r.add_argument("--live", action="store_true", help="make real tool/LLM calls instead of serving recorded fixtures")
    _add_common_gate_flags(r)

    args = p.parse_args(argv)
    args.agent = getattr(args, "agent_opt", None) or args.agent  # allow positional or --agent
    if args.command == "gate":
        return cmd_gate(args)
    if args.command == "replay":
        return cmd_replay(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
