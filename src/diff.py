from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .eval_runner import EvalRunResult
from .schemas import Category


class CategoryDelta(BaseModel):
    category: Category
    prev_correct: int
    curr_correct: int
    total: int
    prev_accuracy: float
    curr_accuracy: float
    delta: float


class CaseFlip(BaseModel):
    case_id: str
    direction: Literal["regression", "improvement"]
    prev_category: Category | None = None
    curr_category: Category | None = None
    prev_summary_score: int | None = None
    curr_summary_score: int | None = None


class EvalDiff(BaseModel):
    previous_run_id: str
    current_run_id: str
    previous_prompt: str
    current_prompt: str
    previous_dataset: str
    current_dataset: str
    pass_rate_delta: float
    summary_score_delta: float | None = None
    latency_delta_ms: float | None = None
    tokens_delta: int = 0
    category_deltas: list[CategoryDelta]
    regressions: list[CaseFlip]
    improvements: list[CaseFlip]
    unchanged_pass: int
    unchanged_fail: int

    @property
    def is_clean(self) -> bool:
        return not self.regressions


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total, 4) if total else 0.0


def diff_runs(previous: EvalRunResult, current: EvalRunResult) -> EvalDiff:
    """Compare two eval runs: deltas, per-category accuracy, and case flips."""
    prev_by_id = {r.case_id: r for r in previous.results}
    curr_by_id = {r.case_id: r for r in current.results}
    shared_ids = prev_by_id.keys() & curr_by_id.keys()

    regressions: list[CaseFlip] = []
    improvements: list[CaseFlip] = []
    unchanged_pass = unchanged_fail = 0
    summary_deltas: list[float] = []
    for case_id in sorted(shared_ids):
        prev, curr = prev_by_id[case_id], curr_by_id[case_id]
        if curr.summary_score is not None and prev.summary_score is not None:
            summary_deltas.append(curr.summary_score - prev.summary_score)
        if prev.category_match and not curr.category_match:
            regressions.append(_flip(case_id, "regression", prev, curr))
        elif not prev.category_match and curr.category_match:
            improvements.append(_flip(case_id, "improvement", prev, curr))
        elif prev.category_match:
            unchanged_pass += 1
        else:
            unchanged_fail += 1

    def _category_delta(category: Category) -> CategoryDelta:
        prev_correct = sum(1 for cid in shared_ids if prev_by_id[cid].expected.category == category and prev_by_id[cid].category_match)
        curr_correct = sum(1 for cid in shared_ids if curr_by_id[cid].expected.category == category and curr_by_id[cid].category_match)
        total = sum(1 for cid in shared_ids if curr_by_id[cid].expected.category == category)
        return CategoryDelta(
            category=category,
            prev_correct=prev_correct,
            curr_correct=curr_correct,
            total=total,
            prev_accuracy=_accuracy(prev_correct, total),
            curr_accuracy=_accuracy(curr_correct, total),
            delta=round(_accuracy(curr_correct, total) - _accuracy(prev_correct, total), 4),
        )

    return EvalDiff(
        previous_run_id=previous.run_id,
        current_run_id=current.run_id,
        previous_prompt=previous.prompt_version,
        current_prompt=current.prompt_version,
        previous_dataset=previous.dataset_version,
        current_dataset=current.dataset_version,
        pass_rate_delta=round(current.pass_rate - previous.pass_rate, 4),
        summary_score_delta=(
            round(sum(summary_deltas) / len(summary_deltas), 4) if summary_deltas else None
        ),
        latency_delta_ms=(
            round(current.avg_latency_ms - previous.avg_latency_ms, 2)
            if current.avg_latency_ms is not None and previous.avg_latency_ms is not None
            else None
        ),
        tokens_delta=current.total_tokens - previous.total_tokens,
        category_deltas=[_category_delta(c) for c in Category],
        regressions=regressions,
        improvements=improvements,
        unchanged_pass=unchanged_pass,
        unchanged_fail=unchanged_fail,
    )


def _flip(case_id: str, direction: str, prev, curr) -> CaseFlip:
    return CaseFlip(
        case_id=case_id,
        direction=direction,
        prev_category=prev.actual.category if prev.actual else None,
        curr_category=curr.actual.category if curr.actual else None,
        prev_summary_score=prev.summary_score,
        curr_summary_score=curr.summary_score,
    )