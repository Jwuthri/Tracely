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


def trigger_gate(api: str, key: str, agent: str, env: str, git_ref: str, pr: int | None) -> dict:
    body = json.dumps({"agent": agent, "env": env, "git_ref": git_ref, "pr_number": pr}).encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/api/gate",
        data=body,
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req))


def case_reason(detail: dict) -> str:
    """A short, human reason for a non-PASS case from the gate's detail payload."""
    d = detail or {}
    bits: list[str] = []
    if d.get("missing_tools"):
        bits.append("missing tools: " + ", ".join(d["missing_tools"]))
    if d.get("erroring_steps"):
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


def cmd_gate(args: argparse.Namespace) -> int:
    api = args.api or os.environ.get("TRACELY_API", "http://localhost:8000")
    key = args.key or os.environ.get("TRACELY_KEY", "tracely_dev_key")
    web_url = args.web_url or os.environ.get("TRACELY_WEB_URL", "")
    agent = args.agent or os.environ.get("TRACELY_AGENT", "")
    if not agent:
        print("error: --agent (or TRACELY_AGENT) is required")
        return 2

    repo, sha, pr = gh_context()
    if args.sha:
        sha = args.sha
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
    markdown = render_markdown(data, web_url, sha)
    write_step_summary(markdown)

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    want_github = args.github or (os.environ.get("GITHUB_ACTIONS") == "true" and token)
    if want_github and not args.no_github:
        if not token:
            print("note: --github requested but no GITHUB_TOKEN; skipping PR check")
        elif not repo:
            print("note: not in a GitHub repo context (no GITHUB_REPOSITORY); skipping PR check")
        else:
            gh = GitHub(token, dry_run=args.dry_run)
            state = {"PASS": "success", "FAIL": "failure"}.get(data["status"], "error")
            desc = f"{data['passed']} passed · {data['failed']} failed · {data['skipped']} skipped"
            target = f"{web_url.rstrip('/')}/gates/{data['id']}" if web_url else ""
            if sha:
                gh.commit_status(repo, sha, state, desc, target)
            if pr:
                gh.upsert_comment(repo, pr, markdown)
            print(f"posted gate check to {repo}" + (f" PR #{pr}" if pr else "") + (" (dry-run)" if args.dry_run else ""))

    return 0 if data["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tracely", description="Tracely CI/CD gate")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gate", help="run an agent's regression suite as a PR gate")
    g.add_argument("agent", nargs="?", help="agent slug (or --agent / TRACELY_AGENT)")
    g.add_argument("--agent", dest="agent_opt", help="agent slug")
    g.add_argument("--env", default=os.environ.get("TRACELY_GATE_ENV", "ci"))
    g.add_argument("--api", help="Tracely API base (TRACELY_API)")
    g.add_argument("--key", help="Tracely ingest key (TRACELY_KEY)")
    g.add_argument("--web-url", help="Tracely web base for links (TRACELY_WEB_URL)")
    g.add_argument("--pr", type=int, help="PR number (else inferred from the Actions event)")
    g.add_argument("--sha", help="commit SHA (else inferred)")
    g.add_argument("--github", action="store_true", help="post a commit status + PR comment")
    g.add_argument("--no-github", action="store_true", help="never touch GitHub even inside Actions")
    g.add_argument("--token", help="GitHub token (else GITHUB_TOKEN)")
    g.add_argument("--dry-run", action="store_true", help="print the GitHub calls instead of sending")
    args = p.parse_args(argv)

    if args.cmd == "gate":
        # allow both `tracely gate planner` and `tracely gate --agent planner`
        args.agent = args.agent_opt or args.agent
        return cmd_gate(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
