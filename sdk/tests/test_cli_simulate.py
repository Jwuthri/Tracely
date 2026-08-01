"""`tracely simulate` — polling, exit codes, and the reason text a reviewer actually reads.

No network: the two API helpers are patched. What matters here is that a non-green run blocks the
merge and says why, since that is the whole job of the command.
"""

from __future__ import annotations

import time

import pytest

from tracely_sdk import cli


# ── reason text ───────────────────────────────────────────────────────────────


def test_transport_failure_is_the_reason():
    assert "Connection refused" in cli.case_reason(
        {"turns": 1, "error": "ConnectError: Connection refused"}
    )


def test_failed_expectations_are_listed():
    reason = cli.case_reason(
        {"failed_expectations": ["turn 2: never offered a refund", "turn 3: wrong total"]}
    )
    assert "never offered a refund" in reason and "wrong total" in reason


def test_failed_evaluators_are_listed():
    """A conversation that sank on the project's own evaluators must still name them, or the PR
    comment shows a red row with no cause."""
    assert "correctness" in cli.case_reason(
        {"failed_scores": ["correctness: invented a refund policy"]}
    )


def test_regression_case_reasons_still_work():
    """The scenario branch must not have broken the replay path's diagnostics."""
    reason = cli.case_reason({"missing_tools": ["get_weather"], "tools_ok": False})
    assert "get_weather" in reason


def test_ungraded_explains_itself():
    note = cli.ungraded_note("UNGRADED", {"turns": 3})
    assert "nothing scored it" in note and "never as a pass" in note


def test_ungraded_note_is_empty_for_other_verdicts():
    assert cli.ungraded_note("FAIL", {"turns": 3}) == ""


# ── markdown ──────────────────────────────────────────────────────────────────


def _data(status="FAIL", **over):
    d = {
        "id": "g1", "agent": "planner", "env": "ci", "status": status,
        "passed": 0, "failed": 1, "skipped": 0, "total": 1,
        "cases": [{
            "title": "Refund flow", "verdict": "FAIL", "scenario_id": "sc1",
            "candidate_trace_id": "conv123",
            "detail": {"turns": 3, "failed_expectations": ["turn 2: no refund offered"]},
        }],
    }
    d.update(over)
    return d


def test_markdown_links_the_conversation():
    """A reviewer should be able to read what was actually said, not just take the verdict's
    word for it."""
    md = cli.render_markdown(_data(), "https://tracely.test", "abc1234")
    assert "https://tracely.test/sessions/conv123" in md
    assert "no refund offered" in md


def test_markdown_does_not_link_a_replayed_case():
    """Only emulated conversations have a thread to open; a regression case must not get a
    /sessions link built from its candidate trace."""
    data = _data()
    data["cases"][0].pop("scenario_id")
    md = cli.render_markdown(data, "https://tracely.test", "abc1234")
    assert "/sessions/" not in md


def test_console_render_does_not_crash_on_an_ungraded_case(capsys):
    data = _data(status="NO_COVERAGE")
    data["cases"][0]["verdict"] = "UNGRADED"
    cli.render_console(data, "abc1234")
    out = capsys.readouterr().out
    assert "UNGRADED" in out and "NO COVERAGE" in out


# ── polling + exit codes ──────────────────────────────────────────────────────


def _args(**over):
    import argparse

    base = dict(
        agent="planner", agent_opt=None, env="ci", api="http://api.test", key="k",
        web_url="", pr=None, sha="deadbeef", github=False, no_github=True, token="",
        dry_run=True, min_pass_rate=None, timeout=30,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_poll_returns_once_the_gate_finishes(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, key):
        calls["n"] += 1
        return {"id": "g1", "finished_at": None} if calls["n"] < 2 else {"id": "g1", "finished_at": "now"}

    # `poll_gate` imports time locally, so patch the module itself.
    monkeypatch.setattr(cli, "_get_json", fake_get)
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    assert cli.poll_gate("http://api.test", "k", "g1", timeout=30, quiet=True)["finished_at"]
    assert calls["n"] == 2


def test_poll_raises_rather_than_reporting_green(monkeypatch):
    """A gate that never finished is not a pass. Timing out has to surface, not fall through."""
    monkeypatch.setattr(cli, "_get_json", lambda url, key: {"id": "g1", "finished_at": None})
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    with pytest.raises(TimeoutError):
        cli.poll_gate("http://api.test", "k", "g1", timeout=0, quiet=True)


@pytest.mark.parametrize(
    "status,code",
    [("PASS", 0), ("FAIL", 1), ("NO_COVERAGE", 1), ("ERROR", 1)],
)
def test_exit_code_blocks_the_merge_on_anything_but_pass(monkeypatch, status, code):
    monkeypatch.setattr(cli, "start_simulation", lambda *a, **k: {"id": "g1"})
    monkeypatch.setattr(cli, "poll_gate", lambda *a, **k: _data(status=status))
    monkeypatch.setattr(cli, "gh_context", lambda: ("", "", None))

    assert cli.cmd_simulate(_args()) == code


def test_a_timeout_exits_non_zero(monkeypatch):
    monkeypatch.setattr(cli, "start_simulation", lambda *a, **k: {"id": "g1"})

    def boom(*a, **k):
        raise TimeoutError("gate g1 did not finish within 30s")

    monkeypatch.setattr(cli, "poll_gate", boom)
    monkeypatch.setattr(cli, "gh_context", lambda: ("", "", None))

    assert cli.cmd_simulate(_args()) == 2


def test_missing_agent_is_a_usage_error(monkeypatch):
    monkeypatch.delenv("TRACELY_AGENT", raising=False)
    assert cli.cmd_simulate(_args(agent=None)) == 2


def test_min_pass_rate_is_forwarded(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        cli, "start_simulation",
        lambda api, key, agent, env, ref, pr, mpr=None: sent.update(rate=mpr) or {"id": "g1"},
    )
    monkeypatch.setattr(cli, "poll_gate", lambda *a, **k: _data(status="PASS"))
    monkeypatch.setattr(cli, "gh_context", lambda: ("", "", None))

    cli.cmd_simulate(_args(min_pass_rate=0.9))
    assert sent["rate"] == 0.9
