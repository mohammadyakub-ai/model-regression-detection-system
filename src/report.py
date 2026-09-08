from __future__ import annotations

import html
from pathlib import Path

from .assessment import EvalAssessment
from .diff import EvalDiff
from .eval_runner import EvalRunResult

_STATUS_BADGE = {
    "pass": "status-pass",
    "warn": "status-warn",
    "fail": "status-fail",
}


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _trend_svg(history: list[EvalRunResult], window: int) -> str:
    """Inline SVG line chart of pass rate and avg summary score over runs."""
    series = history[-window:]
    if not series:
        return "<p>No trend data yet.</p>"
    n = len(series)
    w, h, pad_l, pad_b, pad_t, pad_r = 720, 260, 52, 30, 20, 60
    inner_w, inner_h = w - pad_l - pad_r, h - pad_t - pad_b

    def x(i: int) -> float:
        return pad_l + (inner_w * i / (max(n - 1, 1)))

    def y(v: float, scale: float) -> float:
        return pad_t + inner_h - (inner_h * (v / scale))

    pass_pts = [f"{x(i):.1f},{y(r.pass_rate * 100, 100):.1f}" for i, r in enumerate(series)]
    summary_pts = [
        f"{x(i):.1f},{y((r.avg_summary_score or 0) * 20, 100):.1f}"  # 0-5 -> 0-100
        for i, r in enumerate(series)
    ]

    grid = ""
    for gv in (0, 25, 50, 75, 100):
        gy = y(gv, 100)
        grid += f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" class="grid"/>'
        grid += f'<text x="{pad_l - 6}" y="{gy + 4:.1f}" text-anchor="end" class="axis">{gv}</text>'

    labels = ""
    for i, r in enumerate(series):
        labels += (
            f'<text x="{x(i):.1f}" y="{h - 8}" text-anchor="middle" class="axis">'
            f"{r.prompt_version}</text>"
        )

    return f"""\
<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img" aria-label="score trend">
  {grid}
  <polyline points="{' '.join(pass_pts)}" fill="none" class="line-pass"/>
  <polyline points="{' '.join(summary_pts)}" fill="none" class="line-summary"/>
  <circle cx="{x(n-1):.1f}" cy="{y(series[-1].pass_rate*100,100):.1f}" r="4" class="dot-pass"/>
  {labels}
  <text x="{w - 8}" y="{pad_t + 12}" text-anchor="end" class="legend-pass">pass rate %</text>
  <text x="{w - 8}" y="{pad_t + 30}" text-anchor="end" class="legend-summary">summary avg (x20)</text>
</svg>"""


def _case_rows(flips, current: EvalRunResult, previous: EvalRunResult | None) -> str:
    prev_by_id = {r.case_id: r for r in previous.results} if previous else {}
    curr_by_id = {r.case_id: r for r in current.results}
    rows = []
    for flip in flips:
        prev_res = prev_by_id.get(flip.case_id)
        curr_res = curr_by_id.get(flip.case_id)

        def cell(res, summary_score) -> str:
            if res is None or res.actual is None:
                return '<td class="muted">n/a</td>'
            return (
                f'<td><span class="tag">{html.escape(res.actual.category.value)}</span></td>'
                f"<td>{html.escape(res.actual.summary)}</td>"
                f'<td class="muted">{html.escape((res.actual.raw_output or "")[:200])}</td>'
                f"<td>{summary_score if summary_score is not None else '&ndash;'}</td>"
            )

        rows.append(
            "<tr>"
            f'<td class="mono">{flip.case_id}</td>'
            f'<td class="direction-{flip.direction}">{flip.direction}</td>'
            + cell(prev_res, flip.prev_summary_score)
            + '<td class="arrow">&rarr;</td>'
            + cell(curr_res, flip.curr_summary_score)
            + "</tr>"
        )
    return "".join(rows)


def _category_rows(diff: EvalDiff) -> str:
    rows = []
    for cd in diff.category_deltas:
        direction = "pos" if cd.delta > 0 else "neg" if cd.delta < 0 else ""
        rows.append(
            "<tr>"
            f'<td>{html.escape(cd.category.value)}</td>'
            f"<td>{_fmt_pct(cd.prev_accuracy)}</td>"
            f"<td>{_fmt_pct(cd.curr_accuracy)}</td>"
            f'<td class="delta-{direction}">{cd.delta:+.1%}</td>'
            f"<td>{cd.curr_correct}/{cd.total}</td>"
            "</tr>"
        )
    return "".join(rows)


def _baseline_category_rows(current: EvalRunResult) -> str:
    from collections import Counter

    totals = Counter(r.expected.category for r in current.results)
    correct = Counter(r.expected.category for r in current.results if r.category_match)
    rows = []
    for category in sorted(set(totals) | set(correct)):
        total, ok = totals[category], correct[category]
        rows.append(
            "<tr>"
            f'<td>{html.escape(category.value)}</td>'
            "<td>&ndash;</td>"
            f"<td>{_fmt_pct(ok / total) if total else '&ndash;'}</td>"
            "<td>&ndash;</td>"
            f"<td>{ok}/{total}</td>"
            "</tr>"
        )
    return "".join(rows)


def build_report(
    current: EvalRunResult,
    diff: EvalDiff | None,
    assessment: EvalAssessment,
    history: list[EvalRunResult],
    output_path: str | Path,
    trend_window: int = 10,
    previous: EvalRunResult | None = None,
) -> Path:
    """Generate a self-contained HTML report and write it to output_path.

    diff may be None for a baseline run (no previous run to compare).
    """
    history = sorted(history, key=lambda r: r.created_at)
    if not history or history[-1].run_id != current.run_id:
        history = history + [current]

    badge = _STATUS_BADGE[assessment.status]
    delta_class = "delta-pos" if assessment.delta_pct >= 0 else "delta-neg"
    delta_text = (
        f"{assessment.delta_pct:+.2f} pp"
        if abs(assessment.delta_pct) >= 0.005
        else "no change"
    )

    prev_pct = "&ndash;"
    if previous is not None:
        prev_pct = _fmt_pct(previous.pass_rate)

    regressed_rows = _case_rows(diff.regressions, current, previous) if diff else ""
    improved_rows = _case_rows(diff.improvements, current, previous) if diff else ""
    category_rows = _category_rows(diff) if diff else _baseline_category_rows(current)
    vs_label = f"vs <span class=\"mono\">{html.escape(diff.previous_run_id)}</span>" if diff else "vs (baseline)"

    reasons_html = "".join(f"<li>{html.escape(r)}</li>" for r in assessment.reasons)

    doc = f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Eval report · {html.escape(current.prompt_version)}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
         margin: 0; background: #f6f7f9; color: #1c2733; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 24px; }}
  header {{ border-bottom: 2px solid #e2e6ea; padding-bottom: 16px; margin-bottom: 20px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .meta {{ color: #5b6771; font-size: 13px; }}
  .badge {{ display: inline-block; padding: 3px 12px; border-radius: 999px;
            font-weight: 600; font-size: 13px; color: #fff; }}
  .status-pass {{ background: #1a7f37; }}
  .status-warn {{ background: #d29922; }}
  .status-fail {{ background: #c62828; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px; margin: 16px 0; }}
  .card {{ background: #fff; border: 1px solid #e2e6ea; border-radius: 8px; padding: 12px 16px; }}
  .card .k {{ font-size: 12px; color: #5b6771; }}
  .card .v {{ font-size: 20px; font-weight: 700; margin-top: 2px; }}
  .card .v.delta-pos {{ color: #1a7f37; }} .card .v.delta-neg {{ color: #c62828; }}
  h2 {{ font-size: 16px; margin: 24px 0 8px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border: 1px solid #e2e6ea; border-radius: 8px; overflow: hidden; font-size: 13px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #edf0f3; vertical-align: top; }}
  th {{ background: #f0f2f5; font-size: 12px; text-transform: uppercase; color: #5b6771; }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
  .tag {{ background: #eef2ff; color: #3730a3; padding: 1px 8px; border-radius: 999px; font-size: 12px; }}
  .arrow {{ text-align: center; color: #5b6771; width: 30px; }}
  .direction-regression {{ color: #c62828; font-weight: 600; }}
  .direction-improvement {{ color: #1a7f37; font-weight: 600; }}
  .delta-pos {{ color: #1a7f37; }} .delta-neg {{ color: #c62828; }} .muted {{ color: #5b6771; }}
  .line-pass {{ stroke: #2563eb; stroke-width: 2.5; }}
  .line-summary {{ stroke: #059669; stroke-width: 2; stroke-dasharray: 5 4; }}
  .dot-pass {{ fill: #2563eb; }} .grid {{ stroke: #dfe4ea; stroke-width: 1; }}
  .axis {{ fill: #5b6771; font-size: 11px; }}
  .legend-pass {{ fill: #2563eb; font-size: 12px; }}
  .legend-summary {{ fill: #059669; font-size: 12px; }}
  .panel {{ background: #fff; border: 1px solid #e2e6ea; border-radius: 8px; padding: 16px; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Model Regression Report</h1>
  <div class="meta">
    run <span class="mono">{html.escape(current.run_id)}</span> ·
    prompt <span class="mono">{html.escape(current.prompt_version)}</span> ·
    dataset <span class="mono">{html.escape(current.dataset_version)}</span> ·
    model <span class="mono">{html.escape(current.model)}</span> ·
    {html.escape(current.created_at.isoformat())} ·
    {vs_label}
  </div>
  <p><span class="badge {badge}">{assessment.status.upper()}</span></p>
</header>

<h2>Summary scorecard</h2>
<div class="grid">
  <div class="card"><div class="k">Pass rate</div><div class="v">{_fmt_pct(current.pass_rate)}</div></div>
  <div class="card"><div class="k">Baseline pass rate</div><div class="v">{prev_pct}</div></div>
  <div class="card"><div class="k">Delta</div><div class="v {delta_class}">{delta_text}</div></div>
  <div class="card"><div class="k">Summary avg</div><div class="v">{current.avg_summary_score or '&ndash;'}</div></div>
  <div class="card"><div class="k">Regressions</div><div class="v delta-neg">{len(diff.regressions) if diff else 0}</div></div>
  <div class="card"><div class="k">Improvements</div><div class="v delta-pos">{len(diff.improvements) if diff else 0}</div></div>
  <div class="card"><div class="k">p95 latency</div><div class="v">{current.p95_latency_ms or '&ndash;'} ms</div></div>
  <div class="card"><div class="k">Tokens</div><div class="v">{current.total_tokens}</div></div>
</div>

<h2>Findings</h2>
<div class="panel"><ul>{reasons_html or '<li class="muted">No regressions detected.</li>'}</ul></div>

<h2>Per-category accuracy</h2>
<table><thead><tr><th>Category</th><th>Baseline</th><th>Current</th><th>Delta</th><th>Correct/total</th></tr></thead>
<tbody>{category_rows}</tbody></table>

<h2>Regressed cases (old vs new)</h2>
<table>
<thead><tr><th>Case</th><th>Dir</th><th>Old category</th><th>Old summary</th><th>Old raw</th><th>Old score</th><th></th>
<th>New category</th><th>New summary</th><th>New raw</th><th>New score</th></tr></thead>
<tbody>{regressed_rows or '<tr><td colspan="11" class="muted">No regressions.</td></tr>'}</tbody>
</table>

<h2>Improved cases (old vs new)</h2>
<table>
<thead><tr><th>Case</th><th>Dir</th><th>Old category</th><th>Old summary</th><th>Old raw</th><th>Old score</th><th></th>
<th>New category</th><th>New summary</th><th>New raw</th><th>New score</th></tr></thead>
<tbody>{improved_rows or '<tr><td colspan="11" class="muted">No improvements.</td></tr>'}</tbody>
</table>

<h2>Trend (last {trend_window} runs)</h2>
<div class="panel">{_trend_svg(history, trend_window)}</div>
</div>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.write_text(doc, encoding="utf-8")
    return output_path