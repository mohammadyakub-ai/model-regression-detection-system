import json
import os
import re
from typing import Any

import openai

from .config import PromptConfig
from .schemas import Category, ClassificationResult

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def client_kwargs() -> dict:
    """Connection settings for the LLM provider.

    Reads OPENAI_BASE_URL to point at any OpenAI-compatible endpoint
    (e.g. Groq's https://api.groq.com/openai/v1) and uses GROQ_API_KEY as a
    fallback key when OPENAI_API_KEY is not set.
    """
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise KeyError("OPENAI_API_KEY or GROQ_API_KEY must be set")
    kwargs: dict = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs


def _extract_json(raw: str) -> dict:
    match = _JSON_RE.search(raw)
    if not match:
        raise ValueError(f"no JSON object found in model output: {raw!r}")
    return json.loads(match.group(0))


def build_messages(prompt: PromptConfig, email_text: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": prompt.system_prompt}]
    for example in prompt.few_shot_examples:
        messages.append({"role": "user", "content": example.input})
        messages.append({"role": "assistant", "content": example.output.model_dump_json()})
    messages.append({"role": "user", "content": email_text})
    return messages


def _parse_response(response: Any) -> ClassificationResult:
    raw_output = response.choices[0].message.content
    parsed = _extract_json(raw_output)
    usage = (
        response.usage.model_dump()
        if response.usage is not None and hasattr(response.usage, "model_dump")
        else None
    )
    return ClassificationResult(
        category=parsed["category"],
        summary=parsed["summary"],
        raw_output=raw_output,
        usage=usage,
    )


def classify_email(
    email_text: str,
    prompt: PromptConfig,
    client: openai.OpenAI | None = None,
) -> ClassificationResult:
    """Classify a customer support email using the given prompt config."""
    client = client or openai.OpenAI(**client_kwargs())
    response = client.chat.completions.create(
        model=prompt.model,
        temperature=prompt.temperature,
        response_format={"type": "json_object"},
        messages=build_messages(prompt, email_text),
    )
    return _parse_response(response)


async def classify_email_async(
    email_text: str,
    prompt: PromptConfig,
    client: openai.AsyncOpenAI | None = None,
) -> ClassificationResult:
    """Async variant of classify_email, used by the eval runner for batching."""
    client = client or openai.AsyncOpenAI(**client_kwargs())
    response = await client.chat.completions.create(
        model=prompt.model,
        temperature=prompt.temperature,
        response_format={"type": "json_object"},
        messages=build_messages(prompt, email_text),
    )
    return _parse_response(response)