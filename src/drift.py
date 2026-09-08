from __future__ import annotations

from statistics import mean

from pydantic import BaseModel

from .assessment import EvalAssessment
from .eval_runner import EvalRunResult


class DriftAssessment(BaseModel):
    window: int
    ma_pass_rate: float | None = None
    ma_summary_score: float | None = None
    peak_pass_rate: float
    min_pass_rate: float
    drift_pct_below_peak: float
    detected: bool = False
    reason: str | None = None


def _ma(values: list[float], window: int) -> float | None:
    if not values:
        return None
    return mean(values[-window:])


def assess_drift(
    history: list[EvalRunResult],
    window: int = 7,
    min_pass_rate: float = 0.90,
    drift_pct: float = 5.0,
) -> DriftAssessment:
    """Flag slow drift when the rolling pass-rate average falls below a floor
    or drifts far below the historical peak, even when no single run tripped
    the per-run thresholds."""
    history = sorted(history, key=lambda r: r.created_at)
    peak = max((r.pass_rate for r in history), default=0.0)
    rates = [r.pass_rate for r in history]
    summary_scores = [r.avg_summary_score for r in history if r.avg_summary_score is not None]

    ma_pass = _ma(rates, window)
    ma_summary = _ma(summary_scores, window)

    detected = False
    reason = None
    if ma_pass is not None:
        below_floor = ma_pass < min_pass_rate
        below_peak = (peak - ma_pass) * 100 > drift_pct
        if below_floor:
            detected = True
            reason = (
                f"slow drift: {window}-run moving avg pass rate {ma_pass:.1%} "
                f"is below the {min_pass_rate:.0%} floor"
            )
        elif below_peak:
            detected = True
            reason = (
                f"slow drift: moving avg pass rate {ma_pass:.1%} is more than "
                f"{drift_pct:.0f} pp below the historical peak of {peak:.1%}"
            )

    return DriftAssessment(
        window=window,
        ma_pass_rate=round(ma_pass, 4) if ma_pass is not None else None,
        ma_summary_score=round(ma_summary, 3) if ma_summary is not None else None,
        peak_pass_rate=peak,
        min_pass_rate=min_pass_rate,
        drift_pct_below_peak=drift_pct,
        detected=detected,
        reason=reason,
    )


def evaluate_drift(
    history: list[EvalRunResult],
    current_assessment: EvalAssessment,
    window: int = 7,
    min_pass_rate: float = 0.90,
    drift_pct: float = 5.0,
) -> DriftAssessment:
    """Per-run alerts take precedence: slow drift is only reported when the
    latest run itself did not already trip a per-run warning/fail."""
    if current_assessment.status != "pass":
        return DriftAssessment(
            window=window,
            peak_pass_rate=max((r.pass_rate for r in history), default=0.0),
            min_pass_rate=min_pass_rate,
            drift_pct_below_peak=drift_pct,
            detected=False,
            reason="per-run alert already fired; slow drift check skipped",
        )
    return assess_drift(history, window, min_pass_rate, drift_pct)