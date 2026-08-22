"""The alert-flow engine: run one monitor's step DAG against one firing.

A run is: resolve the DAG (`domain/alerting/flow.py`) → build one context
(`domain/alerting/context.py`) → walk steps in topological order → template each config → call the
runner → append an audit row. No queue between steps, no retries, no parallelism: an alert flow is
short and linear enough that sequential execution inside the caller's task is the right answer, and
the caller is already the thing that just failed a gate or graded a trace.

Every runner returns `(result, error, rendered_config)`. That third element — the POST-Jinja value
of every field actually sent — is what makes a run self-explanatory: the user sees that
`{{ trace.url }}` resolved to a real link, per step, without re-running anything.

Three rules this file exists to keep:

- **Templates are sandboxed.** Every string field is user input from the browser, rendered with
  `jinja2.sandbox.SandboxedEnvironment`; the `python_expression` step is `simpleeval` with an
  allowlist, never `eval`.
- **Outbound URLs are checked twice.** `assert_public_url` runs at save time (the router) *and*
  here, right before the request — the worker shares a network with ClickHouse's HTTP port.
- **The LLM step spends the workspace's own key.** `provider.use_project_key(project_id)` wraps
  it and `llm_enabled()` is checked *inside* the wrap, so a workspace with no key degrades (the
  step fails with a clear message) instead of quietly spending ours.
"""

from __future__ import annotations

import ast
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from simpleeval import (
    EvalWithCompoundTypes,
    FeatureNotAvailable,
    InvalidExpression,
    NameNotDefined,
)
from sqlalchemy.orm import Session

from tracely.config import settings
from tracely.domain.alerting import (
    TRIGGER_NODE_ID,
    ancestor_step_ids,
    build_context,
    ordered_steps,
)
from tracely.infrastructure.db.models import Monitor, MonitorExecution
from tracely.infrastructure.net import UnsafeURL, assert_public_url

log = structlog.get_logger()

_ENV = SandboxedEnvironment(autoescape=False)
_HTTP_TIMEOUT = 20.0
_RESPONSE_TEXT_LIMIT = 8192
_RESPONSE_ERROR_LIMIT = 400
_EXPRESSION_FUNCTIONS: dict[str, Any] = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool, "min": min, "max": max,
    "sum": sum, "abs": abs, "round": round, "sorted": sorted, "any": any, "all": all,
}
# Jinja hands you a STRING: `"False"` is truthy unless you check for it explicitly, which is the
# whole reason this set exists.
_FALSY_RENDERED = {"", "false", "none", "0", "[]", "{}"}

STEP_TYPES = ("condition", "webhook", "slack", "send_email", "llm_prompt", "python_expression")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _render(template: str, ctx: dict) -> str:
    if not template:
        return ""
    return _ENV.from_string(template).render(**ctx)


def _render_leaves(obj: Any, ctx: dict) -> Any:
    if isinstance(obj, str):
        return _render(obj, ctx)
    if isinstance(obj, dict):
        return {k: _render_leaves(v, ctx) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_leaves(v, ctx) for v in obj]
    return obj


def _headers_to_dict(rows: Any) -> dict[str, str]:
    """Headers travel the wire as `[{key, value}]` (an ordered, editable list in the UI) and are a
    dict inside the engine. This is where `Authorization: Bearer …` becomes a real header."""
    if isinstance(rows, dict):
        return {str(k): str(v) for k, v in rows.items()}
    out: dict[str, str] = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("key"):
            out[str(row["key"])] = "" if row.get("value") is None else str(row["value"])
    return out


# ── step runners ──────────────────────────────────────────────────────────────


def _step_condition(config: dict, ctx: dict, **_: Any) -> tuple[Any, str | None, dict]:
    """A Jinja expression rendered to a string. Falsy short-circuits the whole run to `skipped` —
    which is how "only page me for the refund agent" is expressed without a second trigger."""
    raw = config.get("expression") or ""
    rendered = _render(raw, ctx).strip()
    matched = rendered.lower() not in _FALSY_RENDERED
    return {"matched": matched, "expression": rendered}, None, {"expression": rendered, "raw": raw}


def _step_webhook(config: dict, ctx: dict, **_: Any) -> tuple[Any, str | None, dict]:
    """Any verb, any headers, a templated body. The escape hatch that makes the whole feature
    general: PagerDuty, Jira, Linear, an internal endpoint behind a bearer token."""
    url = _render(str(config.get("url") or ""), ctx).strip()
    method = str(config.get("method") or "POST").upper()
    headers = _render_leaves(_headers_to_dict(config.get("headers")), ctx)
    body_template = config.get("body_template")
    body: str | None = None
    if body_template not in (None, ""):
        body = _render(str(body_template), ctx)
        headers = {"Content-Type": "application/json", **headers}
    rendered = {"url": url, "method": method, "headers": headers, "body": body}

    if not url:
        return None, "webhook url is empty", rendered
    try:
        assert_public_url(url)
    except UnsafeURL as exc:
        return None, f"url rejected: {exc}", rendered

    r = httpx.request(
        method, url, headers=headers, content=(body.encode() if body else None), timeout=_HTTP_TIMEOUT
    )
    text = r.text[:_RESPONSE_TEXT_LIMIT]
    if r.status_code >= 400:
        return (
            {"status": r.status_code, "text": text},
            f"HTTP {r.status_code}: {text[:_RESPONSE_ERROR_LIMIT]}",
            rendered,
        )
    return {"status": r.status_code, "text": text}, None, rendered


def _step_slack(config: dict, ctx: dict, **_: Any) -> tuple[Any, str | None, dict]:
    """A Slack incoming webhook with a templated message. `webhook` could do this, but the common
    case shouldn't require hand-writing Slack's JSON."""
    url = str(config.get("url") or "").strip()
    text = _render(str(config.get("text_template") or ""), ctx)
    rendered = {"url": url, "text": text}
    if not url:
        return None, "slack webhook url is empty", rendered
    try:
        assert_public_url(url)
    except UnsafeURL as exc:
        return None, f"url rejected: {exc}", rendered
    r = httpx.post(url, json={"text": text}, timeout=_HTTP_TIMEOUT)
    body = r.text[:_RESPONSE_TEXT_LIMIT]
    if r.status_code >= 400:
        return {"status": r.status_code, "text": body}, f"HTTP {r.status_code}: {body[:200]}", rendered
    return {"status": r.status_code, "text": body}, None, rendered


def _parse_recipients(raw: str) -> list[str]:
    """Accept a Python-list repr OR a comma string. Jinja renders `{{ some_list }}` as
    `"['a@x', 'b@y']"`, so the natural template produces the first shape; a hand-typed field
    produces the second."""
    if not raw:
        return []
    try:
        parsed: Any = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        parsed = raw
    if isinstance(parsed, (list, tuple, set)):
        return [str(x).strip() for x in parsed if str(x).strip()]
    if isinstance(parsed, str):
        return [x.strip() for x in parsed.split(",") if x.strip()]
    return [str(parsed).strip()] if str(parsed).strip() else []


def _step_send_email(config: dict, ctx: dict, **_: Any) -> tuple[Any, str | None, dict]:
    to_raw = _render(str(config.get("to_template") or ""), ctx).strip()
    recipients = _parse_recipients(to_raw)
    subject = _render(str(config.get("subject_template") or ""), ctx)
    body = _render(str(config.get("body_template") or ""), ctx)
    is_html = bool(config.get("body_is_html"))
    rendered = {
        "to_raw": to_raw, "recipients": recipients, "subject": subject,
        "body": body, "body_is_html": is_html,
    }
    if not settings.resend_api_key:
        return None, "email is not configured (RESEND_API_KEY unset)", rendered
    if not recipients:
        return None, "no recipients after parsing the To field", rendered
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={
            "from": settings.email_from,
            "to": recipients,
            "subject": subject,
            ("html" if is_html else "text"): body,
        },
        timeout=_HTTP_TIMEOUT,
    )
    text = r.text[:_RESPONSE_TEXT_LIMIT]
    if r.status_code >= 400:
        return {"status": r.status_code, "text": text}, f"HTTP {r.status_code}: {text[:200]}", rendered
    return {"status": r.status_code, "recipients": recipients, "text": text}, None, rendered


_PY_TYPES: dict[str, Any] = {"string": str, "number": float, "boolean": bool, "array": list[str]}


def _output_model(output_schema: list) -> Any:
    """The user's `output_schema` rows become a pydantic model at runtime.

    `array` maps to `list[str]`, never bare `list`: a bare list emits an `items`-less JSON schema
    and strict-mode providers reject it.
    """
    from pydantic import Field, create_model

    fields: dict[str, Any] = {}
    for row in output_schema:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        py = _PY_TYPES.get(str(row.get("type") or "string").lower(), str)
        fields[str(row["name"])] = (py, Field(description=str(row.get("description") or "")))
    if not fields:
        return None
    return create_model("AlertStepOutput", **fields)


def _step_llm_prompt(
    config: dict, ctx: dict, *, project_id: str, **_: Any
) -> tuple[Any, str | None, dict]:
    """Ask a model something about this failure — "write the Slack message a human would write",
    "classify this into one of our incident categories" — and hand the answer to the next step.

    Runs on the WORKSPACE's OpenRouter key: this is work on their data, so they pay for it, and a
    workspace with no key gets a clear error rather than our invoice.
    """
    from tracely.infrastructure.llm import provider

    model = str(config.get("model") or "").strip() or None
    temperature = float(config.get("temperature") or 0)
    system = _render(str(config.get("system_prompt") or ""), ctx)
    user = _render(str(config.get("user_prompt_template") or ""), ctx)
    schema = config.get("output_schema")
    rendered = {
        "model": model or "(workspace default)",
        "temperature": temperature,
        "system_prompt": system,
        "user_prompt": user,
        "output_schema": schema,
    }
    if not user.strip():
        return None, "user prompt is empty", rendered

    with provider.use_project_key(project_id):
        if not provider.llm_enabled():
            return None, "no OpenRouter key configured for this workspace", rendered
        if isinstance(schema, list) and schema:
            model_cls = _output_model(schema)
            if model_cls is not None:
                out = provider.run_structured_agent(
                    user, response_format=model_cls, system_prompt=system or None,
                    model=model, temperature=temperature,
                )
                return out.model_dump(), None, rendered
        text = provider.run_text_agent(
            user, system_prompt=system or None, model=model, temperature=temperature
        )
    return {"text": text}, None, rendered


def _step_python_expression(config: dict, ctx: dict, **_: Any) -> tuple[Any, str | None, dict]:
    """One expression over the context — counting, slicing, a threshold on a number a template
    can't compute. `simpleeval` with an allowlist: comprehensions and arithmetic yes, `import`,
    attribute-dunder access and function definitions no.

    # ponytail: no wall-clock cap. simpleeval's own length/power limits bound the damage, and
    # SIGALRM only works on the main thread (fine in Celery, wrong under FastAPI's threadpool).
    # If a slow expression ever shows up, cap it in a worker process, not with a signal.
    """
    expr = str(config.get("expression") or "").strip()
    rendered = {"expression": expr}
    if not expr:
        return None, "expression is empty", rendered
    names = {k: v for k, v in ctx.items() if not k.startswith("_")}
    evaluator = EvalWithCompoundTypes(names=names, functions=dict(_EXPRESSION_FUNCTIONS))
    try:
        return evaluator.eval(expr), None, rendered
    except (
        FeatureNotAvailable, NameNotDefined, InvalidExpression, SyntaxError, ValueError, TypeError,
        KeyError, IndexError, AttributeError, ZeroDivisionError,
    ) as exc:
        return None, f"{type(exc).__name__}: {exc}", rendered


_RUNNERS = {
    "condition": _step_condition,
    "webhook": _step_webhook,
    "slack": _step_slack,
    "send_email": _step_send_email,
    "llm_prompt": _step_llm_prompt,
    "python_expression": _step_python_expression,
}


def _run_step(step_type: str, config: dict, ctx: dict, *, project_id: str) -> tuple[Any, str | None, dict]:
    runner = _RUNNERS.get(step_type)
    if runner is None:
        return None, f"unknown step type {step_type!r}", {}
    try:
        return runner(config, ctx, project_id=project_id)
    except TemplateError as exc:
        # A bad template is a user error with a useful message — surface it as the step's error,
        # not as a 500 in whatever pipeline fired the alert.
        return None, f"template error: {exc}", {}
    except Exception as exc:
        log.warning("alert_step_failed", step_type=step_type, error=str(exc))
        return None, f"{type(exc).__name__}: {exc}", {}


# ── the run ───────────────────────────────────────────────────────────────────


def run_flow(
    session: Session,
    monitor: Monitor,
    event: dict,
    *,
    is_test: bool = False,
) -> MonitorExecution:
    """Execute `monitor`'s steps for one firing and persist the execution row.

    Returns the (committed) execution so callers can report per-step results. Never raises for a
    step's own failure: a failed step ends the run with `status="failed"` and an audit row saying
    why, because an alert that breaks must be visible, not thrown into a pipeline that was doing
    something else.
    """
    started = _now()
    ex = MonitorExecution(
        id=str(uuid.uuid4()),
        monitor_id=monitor.id,
        project_id=monitor.project_id,
        trigger_type=str(event.get("type") or ""),
        subject_id=str(event.get("subject_id") or ""),
        status="running",
        started_at=started,
        step_results=[],
        is_test=is_test,
    )
    session.add(ex)
    session.commit()

    steps = list(monitor.steps or [])
    ordered, err = ordered_steps(steps, monitor.flow_layout)
    if err:
        ex.status, ex.completed_at, ex.error = "failed", _now(), err
        session.commit()
        return ex

    base_ctx = build_context(event)
    order_ids = [str(s.id) for s in ordered]
    edges = (monitor.flow_layout or {}).get("edges") if isinstance(monitor.flow_layout, dict) else None

    results: dict[str, Any] = {}
    audit: list[dict] = []
    for step in ordered:
        ancestors = ancestor_step_ids(str(step.id), edges, order_ids)
        ctx = {**base_ctx, "steps": [{"result": results.get(a)} for a in ancestors]}
        step_started = _now()
        out, step_err, rendered = _run_step(
            step.step_type, dict(step.config or {}), ctx, project_id=monitor.project_id
        )
        finished = _now()
        audit.append(
            {
                "step_id": str(step.id),
                "name": step.name,
                "step_type": step.step_type,
                "ok": step_err is None,
                "status": "failed" if step_err else "succeeded",
                "started_at": _iso(step_started),
                "finished_at": _iso(finished),
                "error_message": step_err,
                "result": _jsonable(out),
                "rendered_config": _jsonable(rendered),
                "ancestor_step_ids": ancestors,
            }
        )
        ex.step_results = list(audit)

        if step.step_type == "condition" and step_err is None and isinstance(out, dict) and out.get("matched") is False:
            ex.status, ex.completed_at, ex.error = "skipped", finished, None
            session.commit()
            return ex
        if step_err:
            ex.status, ex.completed_at, ex.error = "failed", finished, step_err
            session.commit()
            return ex
        results[str(step.id)] = out

    ex.status, ex.completed_at, ex.error = "completed", _now(), None
    session.commit()
    return ex


def _jsonable(value: Any) -> Any:
    """Audit rows land in a JSON column — anything a step returns has to survive the trip."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def has_flow(monitor: Monitor) -> bool:
    """Whether this monitor's action is a flow. Without steps it falls back to `channels`, which
    is what every row created before flows existed (and the assistant's `create_alert`) uses."""
    return bool(monitor.steps)


def trigger_node_id() -> str:
    return TRIGGER_NODE_ID
