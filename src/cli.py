from __future__ import annotations

import argparse
import os
import sys

from . import env  # noqa: F401 - ensures .env is loaded
from .golden_dataset import get_dataset, get_latest_dataset
from .pipeline import run_pipeline
from .prompt_registry import get_latest_prompt, get_prompt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="model-eval",
        description="Run the model regression detection pipeline for a prompt + golden dataset.",
    )
    parser.add_argument(
        "--prompt",
        default="latest",
        help="Prompt version_id to test, or 'latest' (default: latest)",
    )
    parser.add_argument(
        "--dataset",
        default="latest",
        help="Dataset version to test, or 'latest' (default: latest)",
    )
    parser.add_argument(
        "--prompts-dir", default="prompts", help="Directory of versioned prompt YAMLs"
    )
    parser.add_argument(
        "--datasets-dir", default="golden_dataset", help="Directory of versioned dataset JSONs"
    )
    parser.add_argument("--runs-dir", default="runs", help="Where eval runs are stored")
    parser.add_argument("--report-dir", default="reports", help="Where reports are written")
    parser.add_argument(
        "--baseline-run", default=None, help="Run ID to compare against (default: previous run)"
    )
    parser.add_argument("--webhook-url", default=None, help="Slack webhook URL (default: env)")
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model in the prompt config at runtime (e.g. a Groq model id)",
    )
    parser.add_argument("--max-concurrency", type=int, default=10)
    args = parser.parse_args(argv)

    prompt = (
        get_latest_prompt(args.prompts_dir)
        if args.prompt == "latest"
        else get_prompt(args.prompts_dir, args.prompt)
    )
    dataset = (
        get_latest_dataset(args.datasets_dir)
        if args.dataset == "latest"
        else get_dataset(args.datasets_dir, args.dataset)
    )

    if args.model:
        prompt = prompt.model_copy(update={"model": args.model})

    result = run_pipeline(
        prompt=prompt,
        dataset=dataset,
        runs_dir=args.runs_dir,
        report_dir=args.report_dir,
        baseline_run=args.baseline_run,
        webhook_url=args.webhook_url,
        max_concurrency=args.max_concurrency,
        drift_window=int(os.environ.get("EVAL_DRIFT_WINDOW", 7)),
        drift_min_pass_rate=float(os.environ.get("EVAL_DRIFT_MIN_PASS", 0.90)),
        drift_pct=float(os.environ.get("EVAL_DRIFT_PCT", 5.0)),
    )

    print(f"run {result.run.run_id}: status={result.assessment.status} "
          f"pass_rate={result.run.pass_rate:.1%} "
          f"delta={result.summary['delta_pp']}pp "
          f"regressions={len(result.summary['regressions'])} "
          f"report={result.report_path}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())