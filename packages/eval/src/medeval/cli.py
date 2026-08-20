"""medeval CLI: validate | probe | run | rejudge | rescore | compare | calibrate."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from medeval.dataset import category_counts, load_cases
from medeval.paths import DATASETS_DIR, REPO_ROOT, REPORTS_DIR


def _load_env() -> None:
    """Load .env once, at the entry point.

    S6.12: credentials used to arrive as a SIDE EFFECT of constructing DemoTarget, so
    `run --target demo` had a judge key and `rejudge` silently did not — 30 batches failed
    on a missing key that was sitting in .env the whole time. Environment loading belongs
    to the process, not to whichever object happens to be built first.
    """
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")


def _force_utf8_stdout() -> None:
    """Make console output encoding-proof (S17.3).

    `medeval compare` renders → and ✅ in its delta table. On Windows the console defaults
    to cp1252, so printing the table raised UnicodeEncodeError — and because the print came
    BEFORE the gate check, the gate never evaluated at all: every run exited 1 from the
    traceback whether quality had regressed or not. A gate that cannot pass is not a gate,
    and an exit code meaning "rendering failed" is indistinguishable from one meaning
    "quality regressed".

    errors="replace" rather than a narrower charset: a display fallback must never again be
    able to take down a verdict.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):  # exotic/detached streams
                reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    _load_env()
    parser = argparse.ArgumentParser(prog="medeval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="validate a golden-set jsonl file")
    p_val.add_argument("dataset", type=Path)

    p_probe = sub.add_parser("probe", help="ask one question against a target")
    p_probe.add_argument("question")
    p_probe.add_argument("--target", default="demo")

    p_run = sub.add_parser("run", help="run a golden set against a target")
    p_run.add_argument("--target", default="demo")
    p_run.add_argument("--dataset", type=Path, default=DATASETS_DIR / "golden_core_v2.jsonl")
    p_run.add_argument("--smoke", type=int, default=None, help="stratified sample of N cases")
    p_run.add_argument("--out", type=Path, default=REPORTS_DIR)
    p_run.add_argument("--skip-ragas", action="store_true", help="deterministic metrics only")

    p_cmp = sub.add_parser("compare", help="delta table between two eval reports")
    p_cmp.add_argument("--before", help="report path, or a target name to use its latest run")
    p_cmp.add_argument("--after", help="report path, or a target name to use its latest run")
    p_cmp.add_argument("--reports", type=Path, default=REPORTS_DIR)
    p_cmp.add_argument("--out", type=Path, default=None, help="write markdown here")
    p_cmp.add_argument(
        "--gate", action="store_true", help="exit 1 if the AFTER run fails a D19 threshold"
    )

    p_res = sub.add_parser("rescore", help="recompute deterministic metrics (no model calls)")
    p_res.add_argument("report", type=Path)
    p_res.add_argument("--dataset", type=Path, default=DATASETS_DIR / "golden_core_v2.jsonl")
    p_res.add_argument("--out", type=Path, default=REPORTS_DIR)

    p_rej = sub.add_parser(
        "rejudge", help="recompute JUDGE metrics from a report's stored contexts (S6.12)"
    )
    p_rej.add_argument("report", type=Path)
    p_rej.add_argument("--dataset", type=Path, default=DATASETS_DIR / "golden_core_v1.jsonl")
    p_rej.add_argument("--out", type=Path, default=REPORTS_DIR)
    p_rej.add_argument("--batch-size", type=int, default=6)
    p_rej.add_argument("--max-attempts", type=int, default=3)
    p_rej.add_argument("--backoff", type=float, default=20.0)
    p_rej.add_argument("--sleep", type=float, default=2.0, help="pause between batches (TPM)")
    p_rej.add_argument(
        "--no-resume", action="store_true", help="ignore any existing judge checkpoint"
    )
    p_rej.add_argument(
        "--metrics", default="", help="comma-separated RAGAS metrics (default: all four)"
    )

    p_cal = sub.add_parser("calibrate", help="judge calibration vs human labels (S19.2)")
    cal_sub = p_cal.add_subparsers(dest="cal_cmd", required=True)

    c_prep = cal_sub.add_parser("prepare", help="sample cases + freeze answers into a sheet")
    c_prep.add_argument("--n", type=int, default=25)
    c_prep.add_argument("--target", default="pipeline")
    c_prep.add_argument("--dataset", type=Path, default=DATASETS_DIR / "golden_core_v2.jsonl")
    c_prep.add_argument("--out", type=Path, default=Path("calibration/labels.jsonl"))
    c_prep.add_argument("--delay", type=float, default=8.0,
                        help="seconds between generations (provider TPM limit)")
    c_prep.add_argument(
        "--proportional", action="store_true",
        help="sample by golden-set proportions instead of balanced per category",
    )

    c_plant = cal_sub.add_parser(
        "plant", help="append deliberately-defective answers so kappa has negatives"
    )
    c_plant.add_argument("--out", type=Path, default=Path("calibration/labels.jsonl"))

    c_score = cal_sub.add_parser("score", help="agreement + Cohen's kappa vs human labels")
    c_score.add_argument("--labels", type=Path, default=Path("calibration/labels.jsonl"))
    c_score.add_argument("--out", type=Path, default=Path("docs/JUDGE_CALIBRATION.md"))
    c_score.add_argument(
        "--skip-judge", action="store_true",
        help="deterministic classifiers only - no judge tokens spent",
    )

    args = parser.parse_args(argv)

    if args.cmd == "validate":
        cases = load_cases(args.dataset)
        print(f"OK: {len(cases)} cases {category_counts(cases)}")
        return 0

    if args.cmd == "probe":
        from medeval.targets import get_target

        ans = get_target(args.target).answer(args.question)
        print(f"answer ({ans.latency_ms:.0f}ms, model={ans.model_id}):\n{ans.answer}\n")
        for i, ctx in enumerate(ans.contexts, start=1):
            print(f"--- context {i} ---\n{ctx[:400]}\n")
        if ans.error:
            print(f"ERROR: {ans.error}", file=sys.stderr)
            return 1
        return 0

    if args.cmd == "calibrate":
        from medeval.calibrate import prepare, score

        if args.cal_cmd == "prepare":
            n, path = prepare(
                args.dataset, args.target, args.n, args.out,
                balanced=not args.proportional, delay=args.delay,
            )
            print(f"\nwrote {n} rows -> {path}")
            print("Fill in each row's `human` fields (yes/no), then run:")
            print("  uv run medeval calibrate score")
            return 0

        if args.cal_cmd == "plant":
            from medeval.calibrate import add_plants

            added, total = add_plants(args.out)
            print(f"added {added} planted rows -> {args.out} ({total} rows total)")
            if added:
                print("Label them exactly as before. The tool will not tell you which\n"
                      "rows are planted, and it must not:\n"
                      "  uv run python packages/eval/tools/label.py")
            return 0

        _results, report_md = score(args.labels, skip_judge=args.skip_judge)
        print(report_md)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report_md, encoding="utf-8")
        print(f"\nwritten: {args.out}")
        return 0

    if args.cmd == "rescore":
        from medeval.compare import load_report
        from medeval.rescore import rescore

        rescored = rescore(load_report(args.report), args.dataset)
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"{rescored.run_id}.json"
        path.write_text(rescored.model_dump_json(indent=2), encoding="utf-8")
        print(f"rescored -> {path}")
        for k, v in sorted(rescored.aggregates.items()):
            print(f"  {k}: {v}")
        return 0

    if args.cmd == "rejudge":
        from medeval.aggregate import applicable_counts, coverage_line
        from medeval.compare import load_report
        from medeval.rejudge import RAGAS_KEYS, checkpoint_path, rejudge

        report = load_report(args.report)
        ckpt = checkpoint_path(args.report)
        if args.no_resume and ckpt.is_file():
            ckpt.unlink()
        rejudged, cov = rejudge(
            report,
            args.dataset,
            batch_size=args.batch_size,
            max_attempts=args.max_attempts,
            backoff_s=args.backoff,
            sleep_between_s=args.sleep,
            checkpoint=ckpt,
            metrics=tuple(m.strip() for m in args.metrics.split(",") if m.strip()) or None,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"{rejudged.run_id}.json"
        path.write_text(rejudged.model_dump_json(indent=2), encoding="utf-8")
        print("")
        print(f"rejudged -> {path}")
        applicable = applicable_counts(rejudged.per_case)
        for k, v in sorted(rejudged.aggregates.items()):
            print(f"  {k}: {v}  (n={coverage_line(k, cov, applicable)})")
        missing = [m for m in RAGAS_KEYS if cov.get(m, 0) < applicable.get(m, 0)]
        if missing:
            print("")
            print(f"WARNING: partial judge coverage for {', '.join(missing)} — read with n.")
        return 0

    if args.cmd == "compare":
        from medeval.compare import compare, gate_failures, latest_report, load_report

        def _resolve(ref: str) -> Path:
            p = Path(ref)
            return p if p.suffix == ".json" and p.exists() else latest_report(args.reports, ref)

        before = load_report(_resolve(args.before))
        after = load_report(_resolve(args.after))
        table = compare(before, after)
        # Decide and persist BEFORE displaying (S17.3). Rendering is the least important
        # thing this command does and the only part that can fail on a terminal's encoding;
        # it must not be able to suppress the verdict or lose the artifact. Previously the
        # print came first, so on a cp1252 console the UnicodeEncodeError meant the gate
        # never evaluated and delta.md was never written — every run exited 1 from the
        # traceback, indistinguishable from a genuine quality regression.
        failures = gate_failures(after) if args.gate else []
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(table, encoding="utf-8")
        print(table)
        if args.out:
            print(f"written: {args.out}")
        if failures:
            print(f"GATE FAILED: {', '.join(failures)}")
            return 1
        return 0

    if args.cmd == "run":
        from medeval.runner import run_eval

        report, path = run_eval(
            target_name=args.target,
            dataset_path=args.dataset,
            out_dir=args.out,
            smoke=args.smoke,
            skip_ragas=args.skip_ragas,
        )
        print(f"\nreport: {path}")
        for k, v in sorted(report.aggregates.items()):
            print(f"  {k}: {v}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
