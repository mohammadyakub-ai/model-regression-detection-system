# Model Regression Detection System

## Demo walkthrough

<video controls preload="metadata" poster="assets/demo-poster.jpg" width="100%" src="assets/CICD-for-AI-prompts.mp4"></video>

A 90-second overview of the system running end to end — a prompt change, the eval pass, the Slack alert, and the diff report.

[▶ Full 4-minute project walkthrough (Google Drive)](https://drive.google.com/file/d/1_H-HhZFL8x6ngjqMky3mFFFltT75p7Bz/view?usp=sharing)

> GitHub only plays raw video files that live in the repository. The clip above is the in-repo teaser; the Drive link holds the complete walkthrough covering every phase.

## What this is

This repository contains a CI/CD-style evaluation pipeline for a customer-support email classifier. Whenever a prompt or model changes, the pipeline runs the feature against a hand-curated golden dataset, scores each case on four dimensions (category accuracy, LLM-judged summary quality, latency, and token usage), diffs the result against the previous run, and reports regressions — per-run via a self-contained HTML report and Slack, and cross-run via a moving-average drift check. Critical regressions block merges. The evaluation logic is fully decoupled from the feature under test through a typed interface contract, so any LLM feature that satisfies the contract can be dropped in and evaluated with zero pipeline changes.

## Repository layout

```
├── prompts/              # Versioned prompt files (YAML) — the code CI runs against
│   ├── classifier_v1.yaml
│   └── classifier_v2.yaml
├── golden_dataset/       # Versioned golden datasets (JSON) — the eval bar
│   └── golden_dataset_v1.json   # 72 hand-curated cases
├── src/
│   ├── env.py            # Loads .env on import
│   ├── contract.py       # Interface contract: Category, ClassifierInput/Output, EvalTarget
│   ├── config.py         # PromptConfig (Pydantic) + YAML loader
│   ├── prompt_registry.py# Prompt version registry (get / latest / duplicate detection)
│   ├── classifier.py     # The feature under test (sync + async variants)
│   ├── golden_dataset.py # Typed dataset models + registry + policy validators
│   ├── eval_runner.py    # Async test runner with bounded concurrency + scoring
│   ├── judge.py          # LLM-as-judge for summary relevance (1-5)
│   ├── run_store.py      # Run persistence (JSON) + previous-run resolution
│   ├── diff.py           # Diff engine: deltas, per-category, regressions/improvements
│   ├── assessment.py     # Threshold assessment (warn/critical) + exit semantics
│   ├── drift.py          # Slow-drift detection via rolling averages
│   ├── report.py         # Self-contained HTML report generator
│   ├── slack.py          # Slack webhook alerting (graceful failure)
│   ├── pipeline.py       # Orchestrates the full eval pipeline
│   └── cli.py            # CLI entry point (`python -m src.cli`)
├── runs/                 # Eval run history (JSON, git-ignored)
├── reports/              # Generated HTML reports + eval-summary.json (git-ignored)
├── .github/workflows/    # GitHub Actions: model-eval on PRs touching prompts/
└── Dockerfile            # Containerized runner
```

## Setup

Requirements: Python 3.11+ (3.10 works), an API key for an OpenAI-compatible LLM provider (OpenAI or Groq), and optionally a Slack incoming-webhook URL.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in your secrets
```

`.env` is git-ignored. The supported variables are:

| Variable | Purpose | Default |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key (platform.openai.com) | — |
| `GROQ_API_KEY` | Groq API key (console.groq.com, free tier available) | — |
| `OPENAI_BASE_URL` | Any OpenAI-compatible endpoint, e.g. `https://api.groq.com/openai/v1` | OpenAI default |
| `SLACK_WEBHOOK_URL` | Alert destination | — |
| `EVAL_WARNING_PCT` | Warn when pass-rate delta exceeds this (percentage points) | `3.0` |
| `EVAL_CRITICAL_PCT` | Fail/block-merge when pass-rate delta exceeds this | `8.0` |
| `EVAL_DRIFT_WINDOW` | Rolling window for drift detection | `7` |
| `EVAL_DRIFT_MIN_PASS` | Drift floor for the moving-average pass rate | `0.90` |
| `EVAL_DRIFT_PCT` | Drift when the moving average falls this far below the historical peak | `5.0` |

Set `OPENAI_API_KEY` **or** `GROQ_API_KEY` — exactly one. The client factory (`client_kwargs()` in `src/classifier.py`) falls back to `GROQ_API_KEY` when `OPENAI_API_KEY` is absent, and points at Groq when `OPENAI_BASE_URL` is set. The pipeline is provider-agnostic: swap providers by changing env vars, not code.

### Running locally

The first run on a machine seeds a baseline (no previous run to diff against, so it always passes):

```bash
.venv/bin/python -m src.cli
```

Every subsequent run diffs against the previous run:

```bash
.venv/bin/python -m src.cli --prompt classifier_v2 --dataset golden_dataset_v1
```

Key flags: `--prompt` / `--dataset` accept a specific `version_id` or `latest` (default); `--baseline-run <id>` diffs against a fixed run instead of the previous one; `--model <id>` overrides the model at runtime without touching the versioned prompt files (e.g. `--model openai/gpt-oss-120b` when running on Groq); `--max-concurrency` caps in-flight requests. Outputs land in `runs/` (history) and `reports/report.html` + `reports/eval-summary.json` (current run). The process exits `0` on pass/warn and `1` on critical regression — that exit code is what CI uses to block merges.

Provider-specific notes: free-tier providers (e.g. Groq) enforce aggressive rate limits, so a run can take several minutes and 429 responses are normal. The runner retries with exponential backoff and honors the `Retry-After` header from 429 responses (`src/eval_runner.py`); lower `--max-concurrency` (2-3) to stay within per-minute limits.

### Running in Docker

```bash
docker build -t model-eval .
docker run --rm \
  -e OPENAI_API_KEY=... -e SLACK_WEBHOOK_URL=... \
  -v "$PWD/runs:/app/runs" -v "$PWD/reports:/app/reports" \
  model-eval
```

For Groq, pass `-e OPENAI_BASE_URL=https://api.groq.com/openai/v1 -e GROQ_API_KEY=...` instead of `OPENAI_API_KEY`, and add `--model openai/gpt-oss-120b` after the image name. The image packages `src/`, `prompts/`, and `golden_dataset/` and runs as a non-root user. `runs/` and `reports/` are volumes so history survives between runs; everything else is read-only inside the image.

## Adding test cases to the golden dataset

Each case is a JSON object with a stable `id`, the raw `input`, an `expected` category+summary (human-verified ground truth), an `expected_difficulty` of `easy|medium|hard`, a `notes` field explaining why the case matters, and an optional `edge_case_types` list (`ambiguous`, `short`, `typo`, `mixed_language`, `sarcasm`).

To add a case, either:

1. **Extend the current bar** — append to `golden_dataset/golden_dataset_v1.json` with a new unique `id` (e.g. `case_0073`). The loader enforces: unique ids, non-empty fields, and that edge-tagged cases are never `easy` — a policy violation fails loudly at load time.
2. **Raise the bar** — copy the file to `golden_dataset_v2.json`, bump `dataset_version` and `created_at`, and edit cases. This is how you change what "good" means historically: old runs keep their dataset version, so diffs across a bar change are explicit rather than silent.

Rule of thumb for new cases: hand-write them, never generate them with an LLM — the dataset is only as trustworthy as the human who labeled it. When a production failure case shows up, add it with a note describing the real incident; this is the mechanism by which the eval bar tracks reality.

## Adjusting thresholds

Thresholds are runtime configuration, never code changes. Set them in `.env` (or the container's environment):

- **Per-run:** `EVAL_WARNING_PCT` and `EVAL_CRITICAL_PCT` are deltas in percentage points of pass rate vs the previous run. Warning means "signal, investigate"; critical means "merge-blocking regression". The `critical` value must be `>=` `warning`.
- **Slow drift:** `EVAL_DRIFT_WINDOW`, `EVAL_DRIFT_MIN_PASS`, and `EVAL_DRIFT_PCT` govern the rolling-average check that catches gradual degradation per-run checks miss. Drift is only reported when the latest run itself passed, so it never double-fires with a per-run alert.

To change the defaults for everyone, edit the defaults in `src/assessment.py` (`ThresholdConfig`) and `src/drift.py`; to change them for one run, pass the environment variables.

## CI/CD

`.github/workflows/model-eval.yml` runs the pipeline on every PR that touches `prompts/**`. It caches `runs/` (via the Actions cache, keyed by branch) so PR diffs have history, uploads the report artifact on every run, posts a structured summary comment on the PR (status, pass-rate delta, regression/improvement case IDs, drift notice), and fails the job on critical regressions.

**Blocking merges** is not a workflow change — it is branch protection. Add `model-eval` as a required status check on the default branch. Because the job exits non-zero on critical regressions, a required check is the enforcement mechanism. Two secrets are needed in the repository: `SLACK_WEBHOOK_URL` plus `OPENAI_API_KEY` (or `GROQ_API_KEY` + `OPENAI_BASE_URL` for Groq).

## Architecture decisions and rationale

- **Prompts are versioned files, not constants.** A prompt is the code under test; versioning it (`version_id`, `created_at`, system prompt, few-shot examples) is what makes the diff meaningful. Without version identity, you cannot attribute a regression to a change.
- **Human-curated golden dataset, versioned as a unit.** Eval quality is bounded by data quality. The dataset is the eval bar, and versioning it makes a deliberate change of bar explicit in the history. The loader enforces dataset policy (unique ids, edge cases are never easy) so the bar cannot drift accidentally.
- **A typed interface contract between feature and evaluator.** `EvalTarget` (a `Protocol`) plus Pydantic input/output models mean the eval engine depends on an interface, not on the classifier. A different feature satisfying the same contract tests identically — this is the property that lets the pipeline outlive its first feature.
- **One code path for prod and test.** `classify_email_async` shares message-building and response-parsing with the sync path, so CI evaluates the exact code that ships, not a test-specific fork.
- **Async runner with a concurrency semaphore.** Batching is bounded, which caps both wall-clock time and token spend rate. Concurrency is a single tuning knob (`--max-concurrency`).
- **Multi-dimensional scoring.** Category match is binary; summary quality is judged by an LLM against the human ideal (1-5); latency and tokens are captured per case. This surfaces regressions that a single accuracy number hides (e.g. a prompt that "improves" accuracy while silently degrading summary fidelity or exploding token cost).
- **Diffing, not just reporting.** The core artifact is the delta vs the previous run: overall and per-category accuracy movement, plus the exact case list that flipped. Per-category deltas catch class-specific drift that the aggregate hides.
- **Separate per-run and drift signals.** A 3%/8% threshold system treats per-run flips as immediate signal; a 7-run moving average treats gradual decline as a distinct failure mode. They are intentionally computed independently and combined only at report time.
- **Self-contained HTML report with escaped output.** No external dependencies, so it is committable, attachable, and safe to render — all LLM-generated text is HTML-escaped to prevent injection.
- **Provider-agnostic client construction.** All API clients are built by a single factory (`client_kwargs()` in `src/classifier.py`) that reads `OPENAI_BASE_URL` and falls back from `OPENAI_API_KEY` to `GROQ_API_KEY`. Every OpenAI-compatible endpoint works with zero contract changes, and the `--model` CLI flag lets a run target a different model without mutating versioned prompt files.
- **Rate-limit resilience for free-tier APIs.** The runner retries with exponential backoff and, on `429` responses, honors the provider's `Retry-After` header. This makes the pipeline usable against rate-limited free tiers (Groq, etc.) rather than only paid accounts with generous limits.
- **Failures degrade, they never crash the pipeline.** A single case error is recorded and retried; a judge failure drops to a `None` score; a missing Slack webhook or webhook error is logged and skipped. Alerting and judging are best-effort; evaluation and diffing are not.
- **Exit code is the CI contract.** `0`/`1` is the only thing the workflow interprets, keeping the pipeline composable with any CI system (GitHub Actions today, anything else later).
- **Containerized with runtime-only secrets.** `runs/` and `reports/` are volumes; the image is otherwise immutable. Secret values are injected at runtime, never baked into the image.