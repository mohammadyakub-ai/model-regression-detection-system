from __future__ import annotations

import asyncio
import statistics
import time
import uuid
from datetime import datetime, timezone

import openai
from pydantic import BaseModel

from .classifier import classify_email_async, client_kwargs
from .config import PromptConfig
from .golden_dataset import GoldenDataset
from .judge import judge_summary_async
from .schemas import ClassificationResult, ClassifierOutput

SUMMARY_PASS_THRESHOLD = 4


def _retry_after_seconds(exc: openai.RateLimitError) -> int | None:
    """Best-effort parse of the Retry-After header from a 429 response."""
    headers = getattr(exc, "headers", None) or {}
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class EvalCaseResult(BaseModel):
    case_id: str
    expected: ClassifierOutput
    actual: ClassificationResult | None = None
    category_match: bool = False
    summary_score: int | None = None
    summary_pass: bool = False
    judge_reason: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class EvalRunResult(BaseModel):
    run_id: str
    prompt_version: str
    dataset_version: str
    model: str
    created_at: datetime
    results: list[EvalCaseResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.category_match)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def summary_pass_rate(self) -> float:
        scored = [r for r in self.results if r.summary_score is not None]
        return sum(1 for r in scored if r.summary_pass) / len(scored) if scored else 0.0

    @property
    def avg_summary_score(self) -> float | None:
        scores = [r.summary_score for r in self.results if r.summary_score is not None]
        return round(statistics.mean(scores), 2) if scores else None

    @property
    def avg_latency_ms(self) -> float | None:
        latencies = [r.latency_ms for r in self.results if r.latency_ms is not None]
        return round(statistics.mean(latencies), 2) if latencies else None

    @property
    def p95_latency_ms(self) -> float | None:
        latencies = sorted(r.latency_ms for r in self.results if r.latency_ms is not None)
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))], 2)

    @property
    def total_tokens(self) -> int:
        return sum(
            (r.actual.usage or {}).get("total_tokens", 0)
            for r in self.results
            if r.actual is not None and r.actual.usage
        )

    @property
    def avg_tokens(self) -> float:
        return round(self.total_tokens / self.total, 2) if self.total else 0.0


async def _run_single_case(
    case,
    prompt: PromptConfig,
    client: openai.AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    retries: int,
    judge_model: str,
    score_summaries: bool,
) -> EvalCaseResult:
    async with semaphore:
        start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                actual = await classify_email_async(case.input, prompt, client=client)
                latency_ms = (time.perf_counter() - start) * 1000
                return await _build_case_result(
                    case, actual, latency_ms, client, judge_model, score_summaries
                )
            except openai.RateLimitError as exc:
                last_error = exc
                if attempt >= retries - 1:
                    break
                delay = _retry_after_seconds(exc)
                if delay is not None:
                    await asyncio.sleep(min(delay, 60))
                else:
                    await asyncio.sleep(1.0 * (2**attempt))
            except Exception as exc:  # noqa: BLE001 - a single case must never kill the run
                last_error = exc
                if attempt >= retries - 1:
                    break
                await asyncio.sleep(0.5 * (2**attempt))
        latency_ms = (time.perf_counter() - start) * 1000
        return EvalCaseResult(
            case_id=case.id,
            expected=case.expected,
            error=f"{type(last_error).__name__}: {last_error}",
            latency_ms=round(latency_ms, 2),
        )


async def _build_case_result(
    case,
    actual: ClassificationResult,
    latency_ms: float,
    client: openai.AsyncOpenAI,
    judge_model: str,
    score_summaries: bool,
) -> EvalCaseResult:
    result = EvalCaseResult(
        case_id=case.id,
        expected=case.expected,
        actual=actual,
        category_match=actual.category == case.expected.category,
        latency_ms=round(latency_ms, 2),
    )
    if score_summaries:
        try:
            judgment = await judge_summary_async(
                case.input,
                case.expected.summary,
                actual.summary,
                model=judge_model,
                client=client,
            )
            result.summary_score = judgment.score
            result.summary_pass = judgment.score >= SUMMARY_PASS_THRESHOLD
            result.judge_reason = judgment.reason
        except Exception as exc:  # noqa: BLE001 - judging must not fail the case
            result.judge_reason = f"judge error: {type(exc).__name__}: {exc}"
    return result


async def run_eval(
    prompt: PromptConfig,
    dataset: GoldenDataset,
    client: openai.AsyncOpenAI | None = None,
    max_concurrency: int = 10,
    retries: int = 8,
    judge_model: str | None = None,
    score_summaries: bool = True,
) -> EvalRunResult:
    """Run every golden case through the feature with bounded async concurrency.

    Per case: category match (binary), LLM-as-judge summary score (1-5),
    latency, and token usage. Judge failures degrade to None scores,
    never to failed cases.
    """
    client = client or openai.AsyncOpenAI(**client_kwargs())
    judge_model = judge_model or prompt.model
    semaphore = asyncio.Semaphore(max_concurrency)

    results = await asyncio.gather(
        *(
            _run_single_case(
                case, prompt, client, semaphore, retries, judge_model, score_summaries
            )
            for case in dataset.cases
        )
    )
    return EvalRunResult(
        run_id=uuid.uuid4().hex[:12],
        prompt_version=prompt.version_id,
        dataset_version=dataset.dataset_version,
        model=prompt.model,
        created_at=datetime.now(timezone.utc),
        results=list(results),
    )


def run_eval_sync(
    prompt: PromptConfig,
    dataset: GoldenDataset,
    client: openai.AsyncOpenAI | None = None,
    max_concurrency: int = 10,
    retries: int = 8,
    judge_model: str | None = None,
    score_summaries: bool = True,
) -> EvalRunResult:
    """Synchronous convenience wrapper around run_eval."""
    return asyncio.run(
        run_eval(
            prompt,
            dataset,
            client=client,
            max_concurrency=max_concurrency,
            retries=retries,
            judge_model=judge_model,
            score_summaries=score_summaries,
        )
    )