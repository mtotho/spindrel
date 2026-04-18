"""LLM-as-judge helper used by experiment_metrics.metric_llm_judge_rubric.

Single async function that takes a rubric + a per-case capture and returns
the parsed JSON judgment (or the raw text if it doesn't parse).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_judge_reply(text: str) -> Any:
    """Parse a judge LLM reply as JSON, with fenced-block fallback."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = _FENCED_JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    return text  # last-resort: return raw text


async def judge_single_case(
    rubric: str,
    case: dict,
    captured: dict,
    args: dict,
) -> Any:
    """Invoke the configured judge LLM on one case + captured response.

    Returns the parsed judgment (a dict in the happy path, or the raw text if
    the model didn't return JSON).
    """
    from app.config import settings
    from app.services.providers import get_llm_client

    model = args.get("judge_model") or settings.COMPACTION_MODEL or settings.DEFAULT_MODEL
    if not model:
        raise RuntimeError("no judge model configured (judge_model arg or DEFAULT_MODEL)")

    case_text = json.dumps(case, default=str)
    captured_text = json.dumps(captured, default=str)
    user_msg = (
        f"INPUT CASE:\n{case_text}\n\n"
        f"BOT CAPTURED OUTPUT:\n{captured_text}\n\n"
        f"Score per the rubric. Reply with ONLY a JSON object."
    )
    messages = [
        {"role": "system", "content": rubric.rstrip()},
        {"role": "user", "content": user_msg},
    ]

    response = await get_llm_client(args.get("provider_id")).chat.completions.create(
        model=model,
        messages=messages,
        temperature=float(args.get("temperature", 0.0)),
        max_tokens=int(args.get("max_tokens", 512)),
    )
    text = response.choices[0].message.content or ""
    return _parse_judge_reply(text)
