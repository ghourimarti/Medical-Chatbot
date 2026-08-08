"""medeval CLI: validate | probe | run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from medeval.dataset import category_counts, load_cases
from medeval.paths import DATASETS_DIR, REPORTS_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="medeval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="validate a golden-set jsonl file")
    p_val.add_argument("dataset", type=Path)

    p_probe = sub.add_parser("probe", help="ask one question against a target")
    p_probe.add_argument("question")
    p_probe.add_argument("--target", default="demo")

    p_run = sub.add_parser("run", help="run a golden set against a target")
    p_run.add_argument("--target", default="demo")
    p_run.add_argument("--dataset", type=Path, default=DATASETS_DIR / "golden_core_v1.jsonl")
    p_run.add_argument("--smoke", type=int, default=None, help="stratified sample of N cases")
    p_run.add_argument("--out", type=Path, default=REPORTS_DIR)
    p_run.add_argument("--skip-ragas", action="store_true", help="deterministic metrics only")

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
