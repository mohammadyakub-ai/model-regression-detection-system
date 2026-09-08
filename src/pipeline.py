from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import openai
from pydantic import BaseModel

from .assessment import EvalAssessment, ThresholdConfig, assess_diff
from .config import PromptConfig
from .diff import EvalDiff, diff_runs
from .drift import DriftAssessment, assess_drift, evaluate_drift
from .eval_runner import EvalRunResult, run_eval_sync
from .golden_dataset import GoldenDataset
from .report import build_report
from .run_store import get_previous_run, save_run
from .slack import send_slack_alert

logger = logging.getLogger(__name__)


class PipelineResult(BaseModel):
    run: EvalRunResult
    previous: EvalRunResult | None = None
    diff: EvalDiff | None = None
    assessment: EvalAssessment
    drift: DriftAssessment
    report_path: str
    summary: dict
    exit_code: int


def run_pipeline(
    prompt: PromptConfig,
    dataset: GoldenDataset,
    runs_dir: str | Path,
    report_dir: str | Path,
    baseline_run: str | None = None,
    webhook_url: str | None = None,
    client: openai.AsyncOpenAI | None = None,
    thresholds: ThresholdConfig | None = None,
    drift_window: int = 7,
    drift_min_pass_rate: float = 0.90,
    drift_pct: float = 5.0,
    max_concurrency: int = 10,
) -> PipelineResult:
    """Run the full eval pipeline for a prompt+dataset and write artifacts.

    Returns a PipelineResult whose exit_code is 0 on pass/warn and 1 on fail
    (critical regression) so CI can block merges on the job exit status.
    """
    runs_dir = Path(runs_dir)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    thresholds = thresholds or ThresholdConfig.from_env()

    run = run_eval_sync(
        prompt, dataset, client=client, max_concurrency=max_concurrency
    )
    save_run(run, runs_dir)

    previous: EvalRunResult | None = None
    if baseline_run:
        from .run_store import load_run

        previous = load_run(baseline_run, runs_dir)
    else:
        previous = get_previous_run(run, runs_dir)

    if previous is None:
        assessment = EvalAssessment(
            status="pass",
            delta_pct=0.0,
            warning_pct=thresholds.warning_pct,
            critical_pct=thresholds.critical_pct,
            regression_count=0,
            improvement_count=0,
            reasons=["Baseline run: no previous run to compare against."],
        )
        drift = DriftAssessment(
            window=drift_window,
            peak_pass_rate=run.pass_rate,
            min_pass_rate=drift_min_pass_rate,
            drift_pct_below_peak=drift_pct,
            detected=False,
            reason="Baseline run: not enough history for drift analysis.",
        )
        diff = None
    else:
        diff = diff_runs(previous, run)
        assessment = assess_diff(diff, thresholds)
        from .run_store import list_runs

        drift = evaluate_drift(
            list_runs(runs_dir),
            assessment,
            window=drift_window,
            min_pass_rate=drift_min_pass_rate,
            drift_pct=drift_pct,
        )

    report_path = _build_report(run, diff, assessment, runs_dir, report_dir, previous)

    summary = _build_summary(run, diff, assessment, drift, report_path)

    (report_dir / "eval-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    if assessment.status != "pass" or drift.detected:
        send_slack_alert(
            diff,
            assessment,
            run,
            report_url=os.environ.get("REPORT_URL", str(report_path)),
            webhook_url=webhook_url,
        )

    exit_code = 0 if assessment.status != "fail" else 1
    return PipelineResult(
        run=run,
        previous=previous,
        diff=diff,
        assessment=assessment,
        drift=drift,
        report_path=str(report_path),
        summary=summary,
        exit_code=exit_code,
    )


def _build_report(
    run, diff, assessment, runs_dir, report_dir, previous
) -> Path:
    from .run_store import list_runs

    return build_report(
        run,
        diff,
        assessment,
        history=list_runs(runs_dir),
        output_path=report_dir / "report.html",
        previous=previous,
    )


def _build_summary(
    run: EvalRunResult,
    diff: EvalDiff | None,
    assessment: EvalAssessment,
    drift: DriftAssessment,
    report_path: Path,
) -> dict:
    return {
        "run_id": run.run_id,
        "prompt": run.prompt_version,
        "dataset": run.dataset_version,
        "model": run.model,
        "created_at": run.created_at.isoformat(),
        "status": assessment.status,
        "pass_rate": run.pass_rate,
        "delta_pp": round(diff.pass_rate_delta * 100, 2) if diff else None,
        "regressions": [f.case_id for f in diff.regressions] if diff else [],
        "improvements": [f.case_id for f in diff.improvements] if diff else [],
        "summary_score_avg": run.avg_summary_score,
        "drift_detected": drift.detected,
        "drift_reason": drift.reason,
        "report_path": str(report_path),
        "blocks_merge": assessment.blocks_merge,
    }