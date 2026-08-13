"""`tracely export` / `tracely_sdk.export_conversations` — the SDK's one read path.

No network: `urlopen` is stubbed. What matters is the part a caller cannot see going wrong — the
request the SDK actually builds (auth header, dropped empty params) and that every NDJSON line
comes back as one conversation.
"""

from __future__ import annotations

import io
import json

import pytest

from tracely_sdk import cli, export

_LINES = b'{"thread_id": "t-1", "turns": 2}\n{"thread_id": "t-2", "turns": 1}\n'


@pytest.fixture
def fake_http(monkeypatch):
    """Capture the Request; replay canned NDJSON."""
    seen: list = []

    def urlopen(req, timeout=None):
        seen.append(req)
        return io.BytesIO(_LINES)

    monkeypatch.setenv("TRACELY_API", "https://tracely.test")
    monkeypatch.setenv("TRACELY_KEY", "k_secret")
    monkeypatch.setattr(export.urllib.request, "urlopen", urlopen)
    return seen


def test_conversations_are_yielded_one_per_line(fake_http):
    convs = list(export.export_conversations())
    assert [c["thread_id"] for c in convs] == ["t-1", "t-2"]


def test_blank_lines_are_skipped(monkeypatch, fake_http):
    monkeypatch.setattr(
        export.urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b'\n{"a": 1}\n\n')
    )
    assert list(export.export_conversations()) == [{"a": 1}]


def test_request_carries_the_key_and_drops_empty_params(fake_http):
    list(export.export_conversations())
    (req,) = fake_http
    assert req.headers["Authorization"] == "Bearer k_secret"
    # limit=0 means "everything" — sending `?limit=` would 422 instead
    assert req.full_url == "https://tracely.test/api/export"


def test_filters_reach_the_query_string(fake_http):
    list(export.export_conversations(limit=5, from_ts="2026-01-01T00:00:00", evals=True))
    (req,) = fake_http
    assert "limit=5" in req.full_url
    assert "from_ts=2026-01-01T00%3A00%3A00" in req.full_url
    assert "evals=true" in req.full_url
    assert "to_ts" not in req.full_url


def test_explicit_api_and_key_beat_the_environment(fake_http):
    list(export.export_conversations(api="http://localhost:8000/", key="k_other"))
    (req,) = fake_http
    assert req.full_url == "http://localhost:8000/api/export"  # trailing slash not doubled
    assert req.headers["Authorization"] == "Bearer k_other"


def test_download_writes_raw_bytes_and_reports_the_size(fake_http, tmp_path):
    dest = tmp_path / "dump.ndjson"
    written = export.download_export(str(dest))
    assert written == len(_LINES)
    assert dest.read_bytes() == _LINES


def test_download_leaves_a_caller_owned_handle_open(fake_http):
    buf = io.BytesIO()
    export.download_export(buf)
    assert not buf.closed and buf.getvalue() == _LINES


def test_cli_export_writes_the_file(fake_http, tmp_path, capsys):
    dest = tmp_path / "out.ndjson"
    assert cli.main(["export", "--out", str(dest), "--limit", "5"]) == 0
    assert [json.loads(x)["thread_id"] for x in dest.read_text().splitlines()] == ["t-1", "t-2"]
    assert "limit=5" in fake_http[0].full_url
    assert str(dest) in capsys.readouterr().err  # progress goes to stderr, stdout stays NDJSON


def test_cli_export_defaults_to_stdout(fake_http, capsysbinary):
    assert cli.main(["export"]) == 0
    assert capsysbinary.readouterr().out == _LINES
