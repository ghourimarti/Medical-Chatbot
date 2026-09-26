"""Seed believable traffic history before a demo recording (docs/DEMO_SCRIPT.md 1a).

WHY this exists: the most common own-goal in a live demo is a dashboard full of empty
rectangles. Grafana panels are built on `rate(...[5m])` windows, and a rate needs several
samples spread over time — asking one question thirty seconds before you hit record gives
you a single spike and a row of flat lines, which reads to a technical client as "the
observability is decorative". Worse, the SAFETY row is the strongest row on the dashboard
and it is blank unless refusals of *several different categories* have actually happened.

So this replays a realistic MIX, paced across a window:

  grounded   ~60%   in-corpus questions that retrieve and cite
  no_answer  ~15%   questions the support threshold should abstain on
  refused    ~25%   emergency / dosage / diagnosis - the three guardrail categories,
                    so `sum by (category) (medbot_refusals_total)` has three bars

plus deliberate REPEATS, because a cache hit-rate panel sitting at 0% invites exactly the
question you do not want to answer on camera.

Deliberately NOT seeded: rate-limit rejections. `medbot_rate_limited_total` is demo material
in its own right (T6), and a counter already climbing before you start makes the live
`make load-guard` shot unreadable. Pacing here stays well under the configured limits
(session 20/min, IP 300/min).

Usage:
  uv run python scripts/demo_seed.py --minutes 20            # the pre-flight default
  uv run python scripts/demo_seed.py --minutes 5 --rpm 6     # quick top-up
  uv run python scripts/demo_seed.py --dry-run               # show the plan, send nothing
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request

# In-corpus. Every one of these was run against the live stack and returned `grounded`
# with citations. Do NOT add a question here without checking it first: corpus coverage is
# uneven, and a question that abstains lands in the wrong bucket and skews the seeded mix.
# (Measured counter-examples, deliberately kept in NO_ANSWER below: "What causes asthma?"
# and "What are the symptoms of appendicitis?" both abstain despite sounding routine.)
GROUNDED = [
    "What is chickenpox?",
    "What are the symptoms of chickenpox?",
    "What are the symptoms of cirrhosis?",
    "What is an abscess?",
    "What are the symptoms of an abscess?",
    "What are the symptoms of anemia?",
    "What is bronchitis?",
    "What are the symptoms of bronchitis?",
    "How is hepatitis transmitted?",
    "What is a migraine?",
    "What are the signs of dehydration?",
]

# Should return kind=no_answer: either out of domain entirely, or in-domain but not
# supported well enough by the corpus to clear the threshold. Both are correct behaviour
# and both belong in the seeded mix, because the dashboard should show that this happens.
NO_ANSWER = [
    "How does CRISPR gene editing work?",
    "What is the capital of France?",
    "Explain quantum entanglement.",
    "What causes asthma?",
    "What are the symptoms of appendicitis?",
]

# The three guardrail categories, kept separate so the SAFETY row shows three bars
# rather than one. If these ever stop refusing, the seeder tells you before the client does.
REFUSED = {
    "emergency": [
        "I'm having chest pain and my left arm is numb, what should I do?",
        "My child swallowed bleach, what do I do right now?",
    ],
    "dosage": [
        "How much ibuprofen should I take for my back pain?",
        "What dose of amoxicillin should I give a 4 year old?",
    ],
    "diagnosis": [
        "Do I have cancer? I have a lump on my neck.",
        "Is my headache a brain tumour?",
    ],
}

MIX = ["grounded"] * 60 + ["no_answer"] * 15 + ["refused"] * 25


def ask(base_url: str, question: str, timeout: float) -> tuple[str, float, int]:
    """Send one question. Returns (kind, seconds, citation_count).

    Errors are reported rather than raised: a seeder that dies at minute 14 of a 20 minute
    run leaves you with a half-seeded dashboard and no idea which half.
    """
    body = json.dumps({"question": question, "stream": False}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/v1/query",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        elapsed = time.monotonic() - start
        return payload.get("kind", "?"), elapsed, len(payload.get("citations") or [])
    except urllib.error.HTTPError as exc:
        return f"http-{exc.code}", time.monotonic() - start, 0
    except Exception as exc:  # noqa: BLE001 - any transport failure is just a bad sample
        return f"error:{type(exc).__name__}", time.monotonic() - start, 0


def build_plan(count: int, repeat_rate: float, rng: random.Random) -> list[str]:
    """Choose the questions up front so --dry-run shows exactly what will be sent."""
    plan: list[str] = []
    asked: list[str] = []
    for _ in range(count):
        # A repeat produces a cache hit, which is the only way the hit-rate panel moves.
        if asked and rng.random() < repeat_rate:
            plan.append(rng.choice(asked))
            continue
        bucket = rng.choice(MIX)
        if bucket == "grounded":
            q = rng.choice(GROUNDED)
        elif bucket == "no_answer":
            q = rng.choice(NO_ANSWER)
        else:
            q = rng.choice(REFUSED[rng.choice(list(REFUSED))])
        plan.append(q)
        asked.append(q)
    return plan


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://localhost:5007")
    p.add_argument("--minutes", type=float, default=20.0, help="window to spread traffic across")
    p.add_argument("--rpm", type=float, default=4.0, help="requests per minute (stay well under 20/min session limit)")
    p.add_argument("--repeat-rate", type=float, default=0.30, help="fraction of asks that repeat an earlier question")
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument("--seed", type=int, default=None, help="fix the RNG for a reproducible run")
    p.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    args = p.parse_args()

    if args.rpm > 15:
        print(f"  refusing --rpm {args.rpm}: the session limit is 20/min and tripping it")
        print("  pollutes medbot_rate_limited_total, which is the T6 shot. Use --rpm 15 or less.")
        return 2

    rng = random.Random(args.seed)
    count = max(1, int(args.minutes * args.rpm))
    interval = (args.minutes * 60.0) / count
    plan = build_plan(count, args.repeat_rate, rng)

    print()
    print(f"  seeding {count} requests over {args.minutes:g} min (~{interval:.1f}s apart) -> {args.base_url}")
    print(f"  repeats: {count - len(set(plan))} of {count} (these become cache hits)")
    if args.dry_run:
        print()
        for i, q in enumerate(plan, 1):
            print(f"    {i:3d}. {q}")
        print("\n  dry run - nothing sent.")
        return 0

    print()
    kinds: dict[str, int] = {}
    failures = 0
    started = time.monotonic()

    for i, question in enumerate(plan, 1):
        kind, elapsed, cites = ask(args.base_url, question, args.timeout)
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind.startswith(("error", "http-")):
            failures += 1
        note = f"{cites} cites" if cites else ""
        print(f"  {i:3d}/{count}  {kind:<12} {elapsed:6.2f}s  {note:<9} {question[:52]}")

        if i < count:
            # Pace against the wall clock, not a fixed sleep: a 12s cache miss must not
            # push the whole window out by minutes.
            target = started + i * interval
            drift = target - time.monotonic()
            if drift > 0:
                time.sleep(drift)

    print()
    print(f"  done in {(time.monotonic() - started) / 60:.1f} min")
    print("  outcome mix: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    if failures:
        print(f"  WARNING {failures} request(s) failed - check the API before recording")
    print()
    print("  now confirm the dashboards are no longer empty:")
    print("    Grafana   http://localhost:5014  -> Medbot - service overview, range 'Last 1 hour'")
    print("    Langfuse  http://localhost:5015  -> Tracing (ingest lags 5-15s)")
    print("    Prometheus  sum by (kind) (medbot_answers_total)")
    print("                sum by (category) (medbot_refusals_total)   <- wants 3 categories")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
