from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .diff import EvalDiff

EvalStatus = Literal["pass", "warn", "fail"]


class ThresholdConfig(BaseModel):
    """Delta thresholds, in percentage points of pass rate."""

    warning_pct: float = Field(default=3.0, ge=0.0)
    critical_pct: float = Field(default=8.0, ge=0.0)

    @model_validator(mode="after")
    def _critical_must_be_at_least_warning(self) -> "ThresholdConfig":
        if self.critical_pct < self.warning_pct:
            raise ValueError("critical_pct must be >= warning_pct")
        return self

    @classmethod
    def from_env(cls) -> "ThresholdConfig":
        return cls(
            warning_pct=float(os.environ.get("EVAL_WARNING_PCT", 3.0)),
            critical_pct=float(os.environ.get("EVAL_CRITICAL_PCT", 8.0)),
        )


class EvalAssessment(BaseModel):
    status: EvalStatus
    delta_pct: float
    warning_pct: float
    critical_pct: float
    regression_count: int
    improvement_count: int
    significant_improvement: bool = False
    reasons: list[str] = Field(default_factory=list)

    @property
    def blocks_merge(self) -> bool:
        return self.status == "fail"


def assess_diff(
    diff: EvalDiff,
    thresholds: ThresholdConfig | None = None,
) -> EvalAssessment:
    """Classify a diff as pass / warn / fail based on configurable deltas.

    Negative delta beyond warning_pct -> warn; beyond critical_pct -> fail.
    Positive delta beyond warning_pct is flagged as a significant improvement
    (pass status either way).
    """
    thresholds = thresholds or ThresholdConfig.from_env()
    delta_pct = round(diff.pass_rate_delta * 100, 2)

    reasons: list[str] = []
    if diff.regressions:
        reasons.append(f"{len(diff.regressions)} regression(s): {', '.join(f.case_id for f in diff.regressions[:5])}{'...' if len(diff.regressions) > 5 else ''}")

    significant_improvement = delta_pct >= thresholds.warning_pct
    if significant_improvement:
        reasons.append(f"pass rate up {delta_pct:+.2f} pp ({len(diff.improvements)} improvement(s))")

    if delta_pct <= -thresholds.critical_pct:
        status: EvalStatus = "fail"
        reasons.append(f"pass rate down {delta_pct:+.2f} pp exceeds critical threshold (-{thresholds.critical_pct:.1f} pp)")
    elif delta_pct <= -thresholds.warning_pct:
        status = "warn"
        reasons.append(f"pass rate down {delta_pct:+.2f} pp exceeds warning threshold (-{thresholds.warning_pct:.1f} pp)")
    else:
        status = "pass"

    return EvalAssessment(
        status=status,
        delta_pct=delta_pct,
        warning_pct=thresholds.warning_pct,
        critical_pct=thresholds.critical_pct,
        regression_count=len(diff.regressions),
        improvement_count=len(diff.improvements),
        significant_improvement=significant_improvement,
        reasons=reasons,
    )