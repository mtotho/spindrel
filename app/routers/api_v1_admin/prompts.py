"""Admin API — AI-assisted prompt generation."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class GeneratePromptIn(BaseModel):
    context: str  # what this prompt field is for (from generateContext prop)
    user_input: str = ""  # description/instruction, partial prompt, or empty


class GeneratePromptOut(BaseModel):
    prompt: str


_META_PROMPT = """\
You are an expert prompt engineer. You write prompts for LLM systems.

PURPOSE: {context}

{user_input_section}

Write a clear, effective, production-quality prompt. Output ONLY the prompt text — no explanations, no markdown fences, no preamble."""


@router.post("/generate-prompt", response_model=GeneratePromptOut)
async def generate_prompt(body: GeneratePromptIn):
    from app.services.providers import get_llm_client

    if body.user_input.strip():
        user_input_section = (
            f"The user described what they want: '{body.user_input}'. "
            "Write a prompt that fulfills this description."
        )
    else:
        user_input_section = "Write a high-quality prompt from scratch for this purpose."

    system_msg = _META_PROMPT.format(
        context=body.context,
        user_input_section=user_input_section,
    )

    model = settings.PROMPT_GENERATION_MODEL or None
    client = get_llm_client(None)

    # If no model configured, use the default model on the LiteLLM proxy
    kwargs: dict = {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": "Generate the prompt now."},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    if model:
        kwargs["model"] = model
    else:
        # LiteLLM requires a model string; use a sensible default
        kwargs["model"] = settings.COMPACTION_MODEL

    resp = await client.chat.completions.create(**kwargs)
    text = (resp.choices[0].message.content or "").strip()

    return GeneratePromptOut(prompt=text)
