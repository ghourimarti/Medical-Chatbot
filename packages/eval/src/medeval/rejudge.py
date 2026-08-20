"""Recompute JUDGE metrics on a saved report, using the contexts stored with it (S6.12b).

Why this exists
---------------
`rescore` recomputes deterministic metrics offline. Judge metrics could not be recomputed
at all: the only remedy for a throttled judge was a full pipeline re-run — 15 minutes of
generation to fix scores whose inputs (question, answer, retrieved contexts) were already
on disk. S6.10 anticipated this and started persisting `contexts` for exactly this purpose;
this module is the consumer that was never written.

The failure it is built against
-------------------------------
A rate-limited judge does not raise. RAGAS returns NaN per row, NaN becomes None, and the
aggregate quietly averages whatever survived — which is how the S6 pipeline report shipped
`answer_relevancy` computed from one of sixty cases. So this module:

  * evaluates in small batches, so one throttled window cannot void the whole run;
  * retries only the cases still missing the metric, with backoff;
  * reports per-metric coverage at the end and makes thin coverage a loud, explicit outcome
    rather than a number that looks complete.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

from medeval.aggregate import aggregate_scores, applicable_counts, coverage_line
from medeval.dataset import load_cases
from medeval.judge import JUDGE_VERSION
from medeval.metrics import ragas_scores
from medeval.schema import CaseResult, EvalCase, EvalReport, TargetAnswer

RAGAS_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
# faithfulness is the metric S6.12 exists for: it is the one that catches an answer that is
# correct but ungrounded, which is the defining failure mode of a medical RAG system.
PRIMARY_METRIC = "faithfulness"


def _batches(rows: Sequence[tuple[EvalCase, TargetAnswer]], size: int) -> Iterator[list]:
    for i in range(0, len(rows), size):
        yield list(rows[i : i + size])


def checkpoint_path(report_path: Path) -> Path:
    """Sidecar holding scores collected so far, so an interrupted run is not lost."""
    return report_path.with_suffix(".judge-partial.json")


def _load_checkpoint(path: Path | None) -> dict[str, dict[str, float | None]]:
    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: dict(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _save_checkpoint(path: Path | None, scores: dict[str, dict[str, float | None]]) -> None:
    if path is None:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(scores, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write cannot corrupt the checkpoint


def _rows_from_report(
    report: EvalReport, dataset_path: Path
) -> tuple[list[tuple[EvalCase, TargetAnswer]], list[str]]:
    """Rebuild judge inputs from the saved report. Only qa cases carry judgeable
    ground truth, and only rows with stored contexts can be judged at all."""
    by_id: dict[str, EvalCase] = {c.id: c for c in load_cases(dataset_path)}
    rows: list[tuple[EvalCase, TargetAnswer]] = []
    skipped: list[str] = []
    for row in report.per_case:
        if row.category != "qa":
            continue
        case = by_id.get(row.case_id)
        if case is None:
            skipped.append(f"{row.case_id}: not in dataset")
            continue
        if not row.contexts:
            skipped.append(f"{row.case_id}: no stored contexts")
            continue
        if row.error:
            skipped.append(f"{row.case_id}: run errored")
            continue
        rows.append(
            (
                case,
                TargetAnswer(
                    answer=row.answer, contexts=list(row.contexts), latency_ms=row.latency_ms
                ),
            )
        )
    return rows, skipped


def rejudge(
    report: EvalReport,
    dataset_path: Path,
    *,
    batch_size: int = 6,
    max_attempts: int = 3,
    backoff_s: float = 20.0,
    sleep_between_s: float = 2.0,
    checkpoint: Path | None = None,
    metrics: tuple[str, ...] | None = None,
) -> tuple[EvalReport, dict[str, int]]:
    """Return (rejudged report, coverage) — judge metrics recomputed from stored contexts."""
    rows, skipped = _rows_from_report(report, dataset_path)
    if not rows:
        raise RuntimeError(
            "nothing to rejudge: no qa rows with stored contexts. Reports written before "
            "S6.10 do not persist contexts and can only be re-judged by re-running the target."
        )

    # Resume. A throttled judge run takes tens of minutes; without this, a timeout or a
    # Ctrl-C discards every call already paid for — which would make this module's whole
    # premise (never re-run what is already on disk) false of the module itself.
    scores: dict[str, dict[str, float | None]] = _load_checkpoint(checkpoint)
    if scores:
        done = sum(1 for v in scores.values() if v.get(PRIMARY_METRIC) is not None)
        print(f"  resuming from checkpoint: {done} case(s) already scored", flush=True)
    pending = [
        (c, a) for c, a in rows if scores.get(c.id, {}).get(PRIMARY_METRIC) is None
    ]
    if not pending:
        print("  checkpoint already covers every case — nothing to re-judge", flush=True)
    for attempt in range(1, max_attempts + 1):
        still_missing: list[tuple[EvalCase, TargetAnswer]] = []
        total_batches = (len(pending) + batch_size - 1) // batch_size
        for bi, batch in enumerate(_batches(pending, batch_size), start=1):
            ids = [c.id for c, _ in batch]
            try:
                got = ragas_scores(batch, only=metrics)
            except Exception as e:  # noqa: BLE001 — a dead batch must not kill the run
                print(f"  attempt {attempt} batch {bi}/{total_batches} FAILED: {e}", flush=True)
                got = {}
            for cid in ids:
                new = {k: v for k, v in got.get(cid, {}).items() if v is not None}
                if new:
                    scores.setdefault(cid, {}).update(new)
            done = sum(1 for cid in ids if scores.get(cid, {}).get(PRIMARY_METRIC) is not None)
            print(
                f"  attempt {attempt} batch {bi}/{total_batches}: "
                f"{done}/{len(ids)} scored for {PRIMARY_METRIC}",
                flush=True,
            )
            _save_checkpoint(checkpoint, scores)  # survive a kill at any batch boundary
            still_missing += [
                (c, a) for c, a in batch if scores.get(c.id, {}).get(PRIMARY_METRIC) is None
            ]
            if sleep_between_s:
                time.sleep(sleep_between_s)

        pending = still_missing
        if not pending:
            break
        if attempt < max_attempts:
            print(f"  {len(pending)} case(s) still unscored — backing off {backoff_s}s", flush=True)
            time.sleep(backoff_s)

    results: list[CaseResult] = []
    for row in report.per_case:
        fresh = scores.get(row.case_id)
        if not fresh:
            results.append(row)
            continue
        merged: dict[str, float | None] = dict(row.scores)
        merged.update(fresh)
        results.append(row.model_copy(update={"scores": merged}))

    agg, cov = aggregate_scores(results)
    applicable = applicable_counts(results)
    notes = [
        *report.notes,
        f"rejudged with {JUDGE_VERSION}",
        "judge coverage: "
        + ", ".join(f"{m}={coverage_line(m, cov, applicable)}" for m in RAGAS_KEYS),
    ]
    if skipped:
        notes.append(f"skipped {len(skipped)} row(s): {'; '.join(skipped[:5])}")
    if pending:
        notes.append(
            f"UNSCORED after {max_attempts} attempts: {len(pending)} case(s) — "
            "coverage below is partial and MUST be read with its n"
        )

    rejudged = report.model_copy(
        update={
            "run_id": f"{report.run_id}-rejudged",
            "judge": JUDGE_VERSION,
            "per_case": results,
            "aggregates": agg,
            "coverage": cov,
            "notes": notes,
        }
    )
    return rejudged, cov
