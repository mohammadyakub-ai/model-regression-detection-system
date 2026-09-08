from __future__ import annotations

import json
import os
import re

import openai
from pydantic import BaseModel, Field, field_validator

from .classifier import _JSON_RE, client_kwargs

JUDGE_SYSTEM_PROMPT = """\
You are an evaluation judge for a customer support email classifier.
You will receive:
- the original customer email
- the ideal summary (human-written ground truth)
- the model's summary (what you must rate)

Rate how well the model's summary captures the customer's request compared
to the ideal summary, on a 1-5 scale:
5 = captures every key fact and the intent, accurate, concise
4 = captures the intent and most key facts, minor omissions
3 = captures the intent but misses important facts, or adds irrelevant detail
2 = only partially related to the request, key facts wrong or missing
1 = unrelated to the request, contradicts the email, or empty

Penalize factual errors or fabricated details not present in the email.
Respond with a JSON object only: {"score": 1-5, "reason": "one short sentence"}"""

_JUDGE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class JudgeResult(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str

    @field_validator("score", mode="before")
    @classmethod
    def _coerce_number(cls, v: object) -> object:
        try:
            return int(v)
        except (TypeError, ValueError):
            return v


def _parse_judge_output(raw: str) -> JudgeResult:
    match = _JUDGE_JSON_RE.search(raw)
    if not match:
        raise ValueError(f"no JSON object found in judge output: {raw!r}")
    return JudgeResult.model_validate(json.loads(match.group(0)))


def _judge_messages(email_text: str, ideal: str, actual: str) -> list[dict[str, str]]:
    user_prompt = f"""\
Email:
{email_text}

Ideal summary:
{ideal}

Model summary:
{actual}"""
    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


async def judge_summary_async(
    email_text: str,
    ideal_summary: str,
    actual_summary: str,
    model: str,
    client: openai.AsyncOpenAI | None = None,
) -> JudgeResult:
    """LLM-as-judge: rate summary relevance 1-5 against the ideal summary."""
    client = client or openai.AsyncOpenAI(**client_kwargs())
    response = await client.chat.completions.create(
        model=model,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=_judge_messages(email_text, ideal_summary, actual_summary),
    )
    return _parse_judge_output(response.choices[0].message.content)