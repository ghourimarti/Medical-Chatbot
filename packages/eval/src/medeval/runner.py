"""Run a golden set against a target, score, and write JSON + markdown reports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from medeval.aggregate import aggregate_scores, applicable_counts, coverage_line
from medeval.dataset import category_counts, dataset_sha256, load_cases, stratified_sample
from medeval.judge import JUDGE_VERSION
from medeval.metrics import deterministic_scores, ragas_scores
from medeval.schema import CaseResult, EvalCase, EvalReport, TargetAnswer
from medeval.targets import get_target

MAX_CASES_PER_RUN = 250  # cost guard: nobody accidentally judges 10k cases


def run_eval(
    target_name: str,
    dataset_path: Path,
    out_dir: Path,
    smoke: int | None = None,
    skip_ragas: bool = False,
) -> tuple[EvalReport, Path]:
    cases = load_cases(dataset_path)
    if smoke is not None:
        cases = stratified_sample(cases, smoke)
    if len(cases) > MAX_CASES_PER_RUN:
        raise RuntimeError(f"{len(cases)} cases exceeds MAX_CASES_PER_RUN={MAX_CASES_PER_RUN}")

    target = get_target(target_name)
    answers: list[tuple[EvalCase, TargetAnswer]] = []
    for i, case in enumerate(cases, start=1):
        ans = target.answer(case.question)
        answers.append((case, ans))
        status = "ERR" if ans.error else "ok"
        print(f"[{i}/{len(cases)}] {case.id} {status} {ans.latency_ms:.0f}ms", flush=True)

    per_case_scores: dict[str, dict[str, float | None]] = {
        c.id: deterministic_scores(c, a) for c, a in answers
    }
    if not skip_ragas:
        qa_rows = [(c, a) for c, a in answers if c.category == "qa"]
        for case_id, scores in ragas_scores(qa_rows).items():
            per_case_scores[case_id].update(scores)

    results = [
        CaseResult(
            case_id=c.id,
            category=c.category,
            scores=per_case_scores[c.id],
            answer=a.answer,
            n_contexts=len(a.contexts),
            contexts=list(a.contexts),  # persisted so judge metrics stay re-scorable
            latency_ms=a.latency_ms,
            error=a.error,
        )
        for c, a in answers
    ]

    _agg, _cov = aggregate_scores(results)
    report = EvalReport(
        run_id=f"{target_name}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
        created_at=datetime.now(UTC),
        target=target_name,
        dataset=dataset_path.name,
        dataset_sha256=dataset_sha256(dataset_path),
        judge=JUDGE_VERSION if not skip_ragas else "skipped",
        n_cases=len(cases),
        aggregates=_agg,
        coverage=_cov,
        per_case=results,
        notes=[f"category_counts={category_counts(cases)}"],
    )
    out_path = _write_reports(report, out_dir)
    return report, out_path


def _write_reports(report: EvalReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{report.run_id}.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    lines = [
        f"# Eval report — {report.run_id}",
        "",
        f"- target: **{report.target}** · dataset: `{report.dataset}` "
        f"(sha256 `{report.dataset_sha256[:12]}…`)",
        f"- judge: {report.judge} · cases: {report.n_cases} · {report.notes[0]}",
        "",
        "| metric | value | n scored |",
        "|---|---|---|",
    ]
    _applicable = applicable_counts(report.per_case)
    lines += [
        f"| {k} | {v} | {coverage_line(k, report.coverage, _applicable)} |"
        for k, v in sorted(report.aggregates.items())
    ]
    worst = [
        r
        for r in sorted(
            (r for r in report.per_case if r.scores.get("faithfulness") is not None),
            key=lambda r: r.scores["faithfulness"] or 0.0,
        )[:3]
    ]
    if worst:
        lines += ["", "## Lowest-faithfulness examples", ""]
        for r in worst:
            score = r.scores["faithfulness"]
            lines += [f"- **{r.case_id}** (faithfulness={score}): {r.answer[:200]}"]
    (out_dir / f"{report.run_id}.md").write_text("\n".join(lines), encoding="utf-8")
    return json_path
