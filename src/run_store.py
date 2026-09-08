from __future__ import annotations

import json
from pathlib import Path

from .eval_runner import EvalRunResult


def save_run(result: EvalRunResult, runs_dir: str | Path) -> Path:
    """Persist an eval run as JSON; returns the written file path."""
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{result.run_id}.json"
    path.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return path


def load_run(run_id: str, runs_dir: str | Path) -> EvalRunResult:
    path = Path(runs_dir) / f"{run_id}.json"
    return EvalRunResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_runs(runs_dir: str | Path) -> list[EvalRunResult]:
    """All runs, oldest first."""
    runs_dir = Path(runs_dir)
    runs = [load_run(p.stem, runs_dir) for p in runs_dir.glob("*.json")]
    return sorted(runs, key=lambda r: r.created_at)


def get_previous_run(current: EvalRunResult, runs_dir: str | Path) -> EvalRunResult | None:
    """The most recent run that finished before the given run, if any."""
    prior = [r for r in list_runs(runs_dir) if r.created_at < current.created_at]
    return prior[-1] if prior else None