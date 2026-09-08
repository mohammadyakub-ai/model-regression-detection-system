from __future__ import annotations

import json
import logging
import os
import urllib.request

from .assessment import EvalAssessment
from .diff import EvalDiff
from .eval_runner import EvalRunResult

logger = logging.getLogger(__name__)

_STATUS_META = {
    "pass": ("✅", "#1a7f37", "PASS"),
    "warn": ("⚠️", "#d29922", "WARN"),
    "fail": ("🔴", "#c62828", "FAIL"),
}


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def build_slack_payload(
    diff: EvalDiff,
    assessment: EvalAssessment,
    current: EvalRunResult,
    report_url: str,
) -> dict:
    emoji, color, label = _STATUS_META[assessment.status]

    prev_pct = _pct(current.pass_rate - diff.pass_rate_delta)
    curr_pct = _pct(current.pass_rate)

    if assessment.delta_pct >= 0:
        headline = (
            f"{len(diff.improvements)} improvement(s), "
            f"accuracy {prev_pct} → {curr_pct} ({assessment.delta_pct:+.2f} pp)"
        )
    else:
        headline = (
            f"{len(diff.regressions)} regression(s) detected, "
            f"accuracy dropped from {prev_pct} to {curr_pct} ({assessment.delta_pct:+.2f} pp)"
        )

    reasons = " • ".join(assessment.reasons) if assessment.reasons else "No regressions detected."

    return {
        "text": f"[{label}] {headline}",
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"{emoji} Eval {label} · {current.prompt_version}"},
                    },
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*"}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": reasons}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": f"<{report_url}|Open full report>"}},
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": (
                                f"run `{current.run_id}` · dataset `{current.dataset_version}` · "
                                f"model `{current.model}` · {current.created_at.isoformat()}"
                            )},
                        ],
                    },
                ],
            }
        ],
    }


def _post_json(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 400:
            raise RuntimeError(f"Slack webhook returned HTTP {response.status}")


def send_slack_alert(
    diff: EvalDiff,
    assessment: EvalAssessment,
    current: EvalRunResult,
    report_url: str,
    webhook_url: str | None = None,
) -> bool:
    """Send the eval result to Slack. Returns False if no webhook is configured."""
    webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set; skipping Slack alert")
        return False
    payload = build_slack_payload(diff, assessment, current, report_url)
    try:
        _post_json(webhook_url, payload)
        return True
    except Exception as exc:  # noqa: BLE001 - alerting must never break the pipeline
        logger.error("Slack alert failed: %s", exc)
        return False