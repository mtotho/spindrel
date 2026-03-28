"""Admin API — AI-assisted prompt generation."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class GeneratePromptIn(BaseModel):
    context: str = ""  # what this prompt field is for (from generateContext prop)
    user_input: str = ""  # description/instruction, partial prompt, or empty
    mode: str = "generate"  # "generate" = full prompt rewrite, "inline" = replace selected text
    surrounding_context: str = ""  # rest of the document (for inline mode)


class GeneratePromptOut(BaseModel):
    prompt: str


_META_PROMPT = """\
You are an expert prompt engineer. You write prompts for LLM systems.

PURPOSE: {context}

{user_input_section}

Write a clear, effective, production-quality prompt. Output ONLY the prompt text — no explanations, no markdown fences, no preamble."""

_INLINE_PROMPT = """\
You are assisting a user who is editing a prompt template. They have selected a portion of their text and want you to generate a replacement.

The selected text may be:
- A question or instruction — generate the answer or fulfillment
- Text to transform or improve — rewrite it appropriately

{surrounding_section}
Produce ONLY the replacement text. No explanations, no markdown fences, no preamble."""


@router.post("/generate-prompt", response_model=GeneratePromptOut)
async def generate_prompt(body: GeneratePromptIn):
    from app.services.providers import get_llm_client

    if body.mode == "inline":
        surrounding_section = ""
        if body.surrounding_context.strip():
            surrounding_section = (
                "SURROUNDING CONTEXT (the rest of the template around the selection):\n"
                f"```\n{body.surrounding_context}\n```\n"
            )
        system_msg = _INLINE_PROMPT.format(surrounding_section=surrounding_section)
        user_msg = body.user_input
    else:
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
        user_msg = "Generate the prompt now."

    model = settings.PROMPT_GENERATION_MODEL or None
    client = get_llm_client(None)

    kwargs: dict = {
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    if model:
        kwargs["model"] = model
    else:
        kwargs["model"] = settings.COMPACTION_MODEL

    resp = await client.chat.completions.create(**kwargs)
    text = (resp.choices[0].message.content or "").strip()

    return GeneratePromptOut(prompt=text)
