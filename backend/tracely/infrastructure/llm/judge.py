"""HTTP call to the LLM judge endpoint. The configured `llm_judge_*` settings target an
OpenAI-compatible /chat/completions API; the request enforces strict JSON output.
"""

from __future__ import annotations

import json
import urllib.request

from tracely.config import settings


def judge(rubric: str, user_in: str, answer: str, tool_outputs: list[str]) -> tuple[float, str]:
    """Returns `(score in 0..1, reason)`. The caller decides PASS/FAIL by comparing to a
    threshold. Raises on transport/HTTP errors — caller should wrap with `try` and skip the
    score on failure."""
    grounding = ""
    if tool_outputs:
        joined = "\n".join(f"- {t}" for t in tool_outputs)
        grounding = f"\n\nTool results the answer must be consistent with:\n{joined}"
    prompt = (
        rubric + " Respond with strict JSON {\"score\": 0..1, \"reason\": \"...\"}.\n\n"
        f"User request:\n{user_in[:2000]}\n\nAgent answer:\n{answer[:2000]}{grounding}"
    )
    body = json.dumps({
        "model": settings.llm_judge_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{settings.llm_judge_base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.llm_judge_api_key}",
            "content-type": "application/json",
        },
    )
    resp = json.load(urllib.request.urlopen(req, timeout=30))
    parsed = json.loads(resp["choices"][0]["message"]["content"])
    return float(parsed.get("score", 0.0)), str(parsed.get("reason", ""))[:500]
