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


# ── connection precedence ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _forget_init(monkeypatch):
    """`init()` writes module state; keep one test's connection out of the next."""
    monkeypatch.setattr(export, "_conn", {})


def test_init_connection_beats_the_environment(fake_http):
    """The read path follows the write path: a process that traces to a workspace exports from
    that workspace, without the connection restated as env vars."""
    export.remember_connection("https://api.example.test/", "tk_from_init")
    list(export.export_conversations())
    (req,) = fake_http
    assert req.full_url == "https://api.example.test/api/export"
    assert req.headers["Authorization"] == "Bearer tk_from_init"


def test_explicit_arguments_beat_init(fake_http):
    export.remember_connection("https://api.example.test", "tk_from_init")
    list(export.export_conversations(api="https://other.test", key="tk_arg"))
    (req,) = fake_http
    assert req.full_url == "https://other.test/api/export"
    assert req.headers["Authorization"] == "Bearer tk_arg"


def test_env_still_applies_when_init_was_never_called(fake_http):
    list(export.export_conversations())  # fake_http sets TRACELY_API / TRACELY_KEY
    (req,) = fake_http
    assert req.full_url == "https://tracely.test/api/export"


def test_init_wires_the_connection_through(monkeypatch, fake_http):
    """The seam that matters: calling init() must actually populate it.

    Handed its own `tracer_provider` and rolled back afterwards — init() otherwise installs the
    global OTel provider, which no monkeypatch can undo and which silently breaks every later test
    that installs an in-memory exporter.
    """
    import tracely_sdk
    from opentelemetry.sdk.trace import TracerProvider

    for attr in ("_initialized", "_provider", "_tracer"):
        monkeypatch.setattr(tracely_sdk, attr, False if attr == "_initialized" else None)
    tracely_sdk.init(
        endpoint="https://wired.test",
        api_key="tk_wired",
        instrument=False,
        tracer_provider=TracerProvider(),
    )
    assert export._conn == {"api": "https://wired.test", "key": "tk_wired"}


def test_init_updates_the_connection_even_when_already_initialised(monkeypatch, fake_http):
    """The bug this guards: an app that already called init() at startup left the read path
    pinned to the first connection, so an explicit init(endpoint=…) in a REPL was silently
    ignored and the export fell back to localhost."""
    import tracely_sdk
    from opentelemetry.sdk.trace import TracerProvider

    export.remember_connection("https://first.test", "tk_first")
    monkeypatch.setattr(tracely_sdk, "_initialized", True)  # pretend startup already ran
    monkeypatch.setattr(tracely_sdk, "_provider", TracerProvider())
    tracely_sdk.init(endpoint="https://second.test", api_key="tk_second", instrument=False)
    assert export._conn == {"api": "https://second.test", "key": "tk_second"}


def test_meta_filter_reaches_the_query_string(fake_http):
    list(export.export_conversations(meta="business_id=2a73b883"))
    (req,) = fake_http
    assert "meta=business_id%3D2a73b883" in req.full_url


def test_cli_passes_meta_through(fake_http, tmp_path):
    dest = tmp_path / "o.ndjson"
    assert cli.main(["export", "--out", str(dest), "--meta", "business_id=A"]) == 0
    assert "meta=business_id%3DA" in fake_http[0].full_url
