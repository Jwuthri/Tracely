"""The in-app assistant — the chat widget in the dashboard's bottom-right corner.

It runs on TRACELY'S key (`provider.use_server_key`), not the customer's — it explains our
product, so it has to work in a workspace that configured no key of its own.

The conversation lives in Postgres (`assistant_chats`), keyed by project + the person who had it,
so closing the laptop and coming back reloads it. The browser sends one message; the server owns
the transcript. Attachments are stored in object storage under the project's prefix and reach the
model two ways: images as content blocks, anything text-shaped inlined into the prompt.

The agent version (Tracely's own MCP tools, the caller's current screen) grows out of `answer()`:
`path` already says what the user is looking at, and the transcript is already server-side.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import structlog

from tracely.config import settings
from tracely.infrastructure.blob import s3
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.llm import provider

log = structlog.get_logger(__name__)

MAX_TURNS = 20  # of the transcript pasted back as context
MAX_CHARS = 4000  # per message — a pasted stack trace must not become the whole prompt
MAX_FILE_CHARS = 20_000  # of one attached text file
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # bigger than this and the request costs more than it's worth
MAX_IMAGES = 3

# Extensions worth reading even when the browser guessed `application/octet-stream` — which it
# does for most of what a developer actually drags in here.
TEXT_EXTS = (
    ".txt", ".md", ".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".log", ".yaml", ".yml",
    ".toml", ".ini", ".env", ".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".sh", ".xml", ".html",
)

SYSTEM = """You are the Tracely assistant, embedded in the Tracely dashboard.

Tracely is trace-native CI/CD for AI agents: a production trace is graded by evaluators, failing
traces are clustered, clusters become regression cases, and those cases gate a pull request. The
trace is the source of truth — there are no hand-authored datasets.

The pages: Dashboard · Traces (conversations → turns → spans, one column per evaluator) ·
Failure clusters · Regression cases · CI gates · Trends · Scenarios · Settings.

How you answer:
- Two short paragraphs at most. Markdown renders; use it sparingly.
- You cannot read this workspace's data or act on the user's behalf yet. When a question needs
  their traces, say so in one line and name the page that shows it.
- Never invent numbers, trace ids, evaluator names or verdicts. An honest "I can't see that from
  here" beats a plausible-looking answer.
- The user may attach files and images. Read what you are given; don't guess at what you aren't."""


def title_for(message: str) -> str:
    """A conversation's name: its opening question, trimmed at a word boundary. No LLM call —
    naming a chat is not worth a round trip, and the first question is what people scan for."""
    line = " ".join(str(message or "").split())
    if len(line) <= 60:
        return line or "New conversation"
    return line[:57].rsplit(" ", 1)[0] + "…"


def _is_text(att: dict) -> bool:
    mime = str(att.get("mime") or "")
    name = str(att.get("name") or "").lower()
    return (
        mime.startswith("text/")
        or mime in ("application/json", "application/xml", "application/x-ndjson")
        or name.endswith(TEXT_EXTS)
    )


def _attachment_text(project_id: str, att: dict) -> str:
    """One attachment as prompt text. Unreadable types are still ANNOUNCED — a model that isn't
    told a PDF arrived will answer as though the user attached nothing."""
    name, mime = att.get("name") or "file", att.get("mime") or "application/octet-stream"
    if not _is_text(att):
        return f"[attached: {name} ({mime}, {att.get('size') or 0} bytes) — not readable as text]"
    try:
        body = s3.get_blob(s3.assistant_blob_key(project_id, str(att["id"]))).decode(
            "utf-8", "replace"
        )
    except Exception as exc:
        log.warning("assistant_attachment_read_failed", name=name, error=str(exc))
        return f"[attached: {name} — could not be read back]"
    clipped = body[:MAX_FILE_CHARS]
    tail = "" if len(body) <= MAX_FILE_CHARS else f"\n… [truncated, {len(body)} chars total]"
    return f"--- {name} ---\n{clipped}{tail}\n--- end {name} ---"


def _image_blocks(project_id: str, attachments: list[dict]) -> list[dict]:
    """The newest turn's images, as OpenAI-style content blocks."""
    blocks = []
    for att in attachments:
        if not str(att.get("mime") or "").startswith("image/") or len(blocks) >= MAX_IMAGES:
            continue
        try:
            raw = s3.get_blob(s3.assistant_blob_key(project_id, str(att["id"])))
        except Exception as exc:
            log.warning("assistant_image_read_failed", id=att.get("id"), error=str(exc))
            continue
        if len(raw) > MAX_IMAGE_BYTES:
            continue
        url = f"data:{att['mime']};base64,{base64.b64encode(raw).decode()}"
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def _transcript(project_id: str, messages: list[dict], path: str) -> str:
    """The stored conversation as one prompt, oldest first.

    ponytail: only the NEWEST turn's files are inlined; earlier ones are named but not re-read.
    Re-sending every attachment every turn multiplies the token bill by the length of the chat.
    Lift the window here if a conversation ever needs to reason across two files at once.
    """
    lines = []
    if path:
        lines.append(f"[the user is currently on the page: {path}]\n")
    tail = messages[-MAX_TURNS:]
    for i, m in enumerate(tail):
        who = "Assistant" if m.get("role") == "assistant" else "User"
        body = str(m.get("content") or "")[:MAX_CHARS].strip()
        attachments = m.get("attachments") or []
        if attachments and i == len(tail) - 1:
            body += "\n\n" + "\n\n".join(_attachment_text(project_id, a) for a in attachments)
        elif attachments:
            names = ", ".join(str(a.get("name") or "file") for a in attachments)
            body += f"\n[earlier attachments: {names}]"
        lines.append(f"{who}: {body}")
    return "\n\n".join(lines)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def answer(
    project_id: str,
    user_id: str | None,
    *,
    chat_id: str | None,
    message: str,
    attachments: list[dict] | None = None,
    path: str = "",
) -> dict:
    """One turn: load the conversation, ask the model, store both halves.

    Returns `{chat_id, title, reply}`, or `{disabled: True}` when this workspace has no LLM key —
    a state the widget renders (a link to Settings), not an error to swallow. A failed turn is
    NOT stored: history should hold the conversation that happened, not the one that errored.
    """
    attachments = attachments or []
    with SyncSessionLocal() as s:
        row = repo.assistant_chat_get(s, project_id, user_id, chat_id) if chat_id else None
        history = list(row.messages or []) if row else []
        existing_title = row.title if row else ""
    history.append(
        {"role": "user", "content": message, "attachments": attachments, "ts": _now()}
    )

    # OUR key, deliberately: the assistant explains Tracely, so it must answer in a workspace
    # that has configured no key of its own (CLAUDE.md's one exception to `use_project_key`).
    # `llm_enabled()` is checked INSIDE the wrap because under REQUIRE_PROJECT_LLM_KEY an
    # unscoped call fails closed — "we pay for this one" must not look like a forgot-to-wrap bug.
    with provider.use_server_key():
        if not provider.llm_enabled():
            return {"disabled": True}
        text = _transcript(project_id, history, path)
        images = _image_blocks(project_id, attachments)
        prompt = [{"type": "text", "text": text}, *images] if images else text
        reply = provider.run_text_agent(
            prompt,
            system_prompt=SYSTEM,
            model=settings.assistant_model,
            temperature=0.3,
            reasoning_effort=settings.assistant_reasoning_effort,
            # This one call spends OUR credit, so log what it cost and for whom — otherwise the
            # only place the assistant's bill shows up is the OpenRouter invoice, undifferentiated.
            on_usage=lambda usage: log.info(
                "assistant_usage",
                project_id=project_id,
                images=len(images),
                attachments=len(attachments),
                **usage,
            ),
        )

    history.append({"role": "assistant", "content": reply.strip(), "ts": _now()})
    with SyncSessionLocal() as s:
        saved = repo.assistant_chat_save(
            s,
            project_id,
            user_id,
            chat_id=chat_id,
            messages=history,
            title=existing_title or title_for(message),
        )
        return {"chat_id": saved.id, "title": saved.title, "reply": reply.strip()}
