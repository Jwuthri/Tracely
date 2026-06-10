"""Evaluator (= evaluation column) management API: CRUD + templates + generate.

The evaluators router does its Postgres work through the SYNC `SyncSessionLocal` (same pattern
as cases/clusters), so this module overrides the conftest `engine` with a file-backed SQLite db
that a sync engine can share, and points the router's sessionmaker at it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from tracely.infrastructure.db import models
from tracely.infrastructure.db.base import Base

_TABLES = [
    models.Project.__table__,
    models.IngestKey.__table__,
    models.User.__table__,
    models.Membership.__table__,
    models.Invitation.__table__,
    models.Evaluator.__table__,
]


@pytest_asyncio.fixture
async def engine(tmp_path):
    """File-backed SQLite (overrides conftest's :memory: engine for this module) so the sync
    sessionmaker used by the evaluators router can see the same database."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    yield eng
    await eng.dispose()


@pytest.fixture
def sync_db(tmp_path, monkeypatch, engine):
    sync_eng = create_engine(f"sqlite:///{tmp_path}/test.db")
    maker = sessionmaker(sync_eng)
    import tracely.api.routers.evaluators as evaluators_router

    monkeypatch.setattr(evaluators_router, "SyncSessionLocal", maker)
    yield maker
    sync_eng.dispose()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _owner_token(client) -> str:
    r = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def test_workspace_bootstrap_seeds_recommended_evaluators(client, sync_db):
    tok = await _owner_token(client)
    r = await client.get("/api/evaluators", headers=_bearer(tok))
    assert r.status_code == 200, r.text
    names = {e["score_name"] for e in r.json()}
    # the five recommended checks install on workspace bootstrap…
    assert {"tracely.run.outcome", "tracely.tool.success", "tracely.run.quality"} <= names
    # …library-only metrics don't
    assert "tracely.conv.goal_success" not in names


async def test_create_update_delete_evaluator(client, sync_db):
    tok = await _owner_token(client)
    created = await client.post(
        "/api/evaluators",
        headers=_bearer(tok),
        json={
            "name": "Politeness Check",
            "level": "AGENT_RUN",
            "config": {"prompt": "Grade politeness.", "output_type": "score", "threshold": 0.5},
        },
    )
    assert created.status_code == 200, created.text
    e = created.json()
    assert e["kind"] == "llm_judge"
    assert e["score_name"] == "custom.politeness_check"
    assert e["config"]["threshold"] == 0.5

    # same name again → score_name gets a suffix instead of colliding
    dup = await client.post(
        "/api/evaluators", headers=_bearer(tok), json={"name": "Politeness Check"}
    )
    assert dup.json()["score_name"] == "custom.politeness_check_2"

    patched = await client.patch(
        f"/api/evaluators/{e['id']}",
        headers=_bearer(tok),
        json={"enabled": False, "config": {"prompt": "Stricter.", "output_type": "boolean"}},
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["config"]["output_type"] == "boolean"

    deleted = await client.delete(f"/api/evaluators/{e['id']}", headers=_bearer(tok))
    assert deleted.status_code == 200
    again = await client.delete(f"/api/evaluators/{e['id']}", headers=_bearer(tok))
    assert again.status_code == 404


async def test_create_rejects_bad_level_and_kind(client, sync_db):
    tok = await _owner_token(client)
    bad_level = await client.post(
        "/api/evaluators", headers=_bearer(tok), json={"name": "x", "level": "BANANAS"}
    )
    assert bad_level.status_code == 400
    bad_kind = await client.post(
        "/api/evaluators", headers=_bearer(tok), json={"name": "x", "kind": "python"}
    )
    assert bad_kind.status_code == 400


async def test_templates_listing_marks_installed(client, sync_db):
    tok = await _owner_token(client)
    r = await client.get("/api/evaluators/templates", headers=_bearer(tok))
    assert r.status_code == 200
    by_name = {t["score_name"]: t for t in r.json()}
    assert by_name["tracely.run.outcome"]["installed"] is True
    goal = by_name["tracely.conv.goal_success"]
    assert goal["installed"] is False
    assert goal["level"] == "CONVERSATION"
    assert goal["kind"] == "llm_judge"
    # step-level library entry rides on the SPAN level
    assert by_name["tracely.step.tool_choice"]["level"] == "SPAN"


async def test_evaluators_are_project_scoped(client, sync_db, make_workspace):
    tok = await _owner_token(client)
    # a second, separate workspace authed via its ingest key
    await make_workspace("other", "tk_other_key", "other@x.test")
    r = await client.post(
        "/api/evaluators", headers=_bearer("tk_other_key"), json={"name": "Other Metric"}
    )
    assert r.status_code == 200, r.text
    other_id = r.json()["id"]

    mine = await client.get("/api/evaluators", headers=_bearer(tok))
    assert other_id not in {e["id"] for e in mine.json()}

    # cross-project mutation is a 404
    stolen = await client.delete(f"/api/evaluators/{other_id}", headers=_bearer(tok))
    assert stolen.status_code == 404


async def test_models_endpoint_static_fallback(client, sync_db, monkeypatch):
    from tracely.config import settings
    from tracely.infrastructure.llm import provider

    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(provider, "_openrouter_model_names", lambda: {})
    tok = await _owner_token(client)
    r = await client.get("/api/evaluators/models", headers=_bearer(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default"].startswith("openai/")
    ids = [m["id"] for m in body["models"]]
    assert "openai/gpt-5.4-nano" in ids
    assert len(ids) >= 8 and all(m["label"] for m in body["models"])


async def test_models_endpoint_legacy_key_offers_only_openai(client, sync_db, monkeypatch):
    """With only the legacy direct endpoint configured, non-openai OpenRouter ids can't be
    served — the selector narrows instead of offering models that would always fail."""
    from tracely.config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "llm_judge_api_key", "legacy-key")
    tok = await _owner_token(client)
    r = await client.get("/api/evaluators/models", headers=_bearer(tok))
    ids = [m["id"] for m in r.json()["models"]]
    assert ids and all(i.startswith("openai/") for i in ids)


async def test_models_endpoint_filters_to_available(client, sync_db, monkeypatch):
    from tracely.infrastructure.llm import provider

    monkeypatch.setattr(
        provider, "_openrouter_model_names",
        lambda: {"openai/gpt-5.4-nano": "OpenAI: GPT-5.4 Nano"},
    )
    tok = await _owner_token(client)
    r = await client.get("/api/evaluators/models", headers=_bearer(tok))
    assert r.json()["models"] == [{"id": "openai/gpt-5.4-nano", "label": "OpenAI: GPT-5.4 Nano"}]


async def test_generate_json_draft_builds_schema(client, sync_db, monkeypatch):
    from tracely.config import settings
    from tracely.domain.evaluation.generation import GeneratedEvaluatorDraft, GeneratedSchemaField
    from tracely.infrastructure.llm import provider

    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(
        provider, "run_structured_agent",
        lambda prompt, *, response_format, system_prompt=None, model=None, temperature=0.0:
            GeneratedEvaluatorDraft(
                name="Intent classifier",
                description="Classifies the user's intent.",
                level="AGENT_RUN",
                output_type="json",
                prompt="Classify the intent.",
                schema_fields=[
                    GeneratedSchemaField(name="intent", type="enum", enum_values=["a", "b"], required=True),
                    GeneratedSchemaField(name="bad name!", type="string"),  # dropped: not an identifier
                    GeneratedSchemaField(name="reasoning", type="string", required=True),
                ],
            ),
    )
    tok = await _owner_token(client)
    r = await client.post(
        "/api/evaluators/generate", headers=_bearer(tok), json={"description": "classify intent"}
    )
    assert r.status_code == 200, r.text
    schema = r.json()["config"]["output_schema"]
    assert schema["properties"]["intent"]["enum"] == ["a", "b"]
    assert "bad name!" not in schema["properties"]
    assert schema["required"] == ["intent", "reasoning"]


async def test_generate_without_llm_key_is_503(client, sync_db, monkeypatch):
    from tracely.config import settings

    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "llm_judge_api_key", "")
    tok = await _owner_token(client)
    r = await client.post(
        "/api/evaluators/generate", headers=_bearer(tok), json={"description": "politeness"}
    )
    assert r.status_code == 503


async def test_generate_returns_normalized_draft(client, sync_db, monkeypatch):
    from tracely.config import settings
    from tracely.domain.evaluation.generation import GeneratedEvaluatorDraft
    from tracely.infrastructure.llm import provider

    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(
        provider,
        "run_structured_agent",
        lambda prompt, *, response_format, system_prompt=None, model=None, temperature=0.0:
            GeneratedEvaluatorDraft(
                name="Politeness",
                description="Checks politeness.",
                level="agent_run",  # case-normalized
                output_type="SCORE",
                prompt="Grade the reply's politeness.",
                threshold=0.7,
            ),
    )
    tok = await _owner_token(client)
    r = await client.post(
        "/api/evaluators/generate", headers=_bearer(tok), json={"description": "politeness"}
    )
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["kind"] == "llm_judge"
    assert draft["level"] == "AGENT_RUN"
    assert draft["config"]["output_type"] == "score"
    assert draft["config"]["threshold"] == 0.7
    assert draft["config"]["prompt"].startswith("Grade")
