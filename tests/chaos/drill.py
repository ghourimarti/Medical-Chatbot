"""P5.3 chaos drills — dependency failure against REAL processes.

Why this exists when unit tests already cover the degradation paths: those tests use fakes
that raise instantly on command. A real dependency does not fail that politely.

  * A stopped container REFUSES connections (fast). A wedged one ACCEPTS and never answers
    (slow) — only the second exercises timeout handling, and only the second is what an
    overloaded dependency actually looks like.
  * Recovery needs the connection POOL to heal, not just the dependency. A fake never had a
    pool, so "it works again after the outage" is genuinely untested until now.
  * Fail-open and fail-safe are opposite requirements living in one request path: caching
    must degrade to slower (D10), quotas must degrade to stricter (D20). A drill is how you
    find out that one of them silently took the other's behaviour.

SAFETY: this script only STOPS and STARTS containers. It never runs `docker rm`, never
touches volumes, and only acts on the container names passed to it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

API = "http://localhost:1107"

# Every probe MUST be a cache miss, or the drill proves nothing.
#
# First run of this harness reused one question and reported that Qdrant could be stopped
# with zero impact — because every probe was served from the response cache and never
# touched retrieval at all. A chaos drill that accidentally tests the cache will always
# report success, which is the most dangerous way for a drill to be wrong.
_QUESTION_POOL = [
    "What are the symptoms of pneumonia?",
    "What causes kidney stones?",
    "How is epilepsy diagnosed?",
    "What is rheumatoid arthritis?",
    "What are the signs of hypothyroidism?",
    "How is hepatitis B transmitted?",
    "What is the treatment for gout?",
    "What causes migraine headaches?",
    "What are the symptoms of Lyme disease?",
    "How is osteoporosis prevented?",
    "What is celiac disease?",
    "What causes cataracts?",
    "What are the symptoms of shingles?",
    "How is psoriasis treated?",
    "What is sickle cell anemia?",
    "What causes gallstones?",
    "What are the symptoms of meningitis?",
    "How is glaucoma detected?",
    "What is Crohn's disease?",
    "What causes tinnitus?",
    "What are the symptoms of mononucleosis?",
    "How is bronchitis treated?",
    "What is scoliosis?",
    "What causes eczema?",
    "What are the symptoms of appendicitis?",
    "How is anemia diagnosed?",
    "What is emphysema?",
    "What causes vertigo?",
    "What are the symptoms of measles?",
    "How is diabetes managed?",
]
_used = 0


def next_question() -> str:
    """A distinct question per probe, so every request is a genuine cache miss."""
    global _used
    q = _QUESTION_POOL[_used % len(_QUESTION_POOL)]
    _used += 1
    return q


@dataclass
class Probe:
    ok: bool
    status: int
    kind: str | None
    latency_ms: float
    detail: str = ""
    question: str = ""


@dataclass
class DrillResult:
    name: str
    container: str
    steady: Probe | None = None
    during: list[Probe] = field(default_factory=list)
    recovered: Probe | None = None
    recovery_seconds: float | None = None
    notes: list[str] = field(default_factory=list)


def docker(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=120
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def probe(*, question: str | None = None, timeout: float = 60.0) -> Probe:
    """One real request through the whole stack."""
    question = question or next_question()
    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"{API}/api/v1/query",
            json={"question": question, "stream": False},
            timeout=timeout,
        )
    except Exception as e:  # transport-level failure is itself a result
        return Probe(
            ok=False,
            status=0,
            kind=None,
            latency_ms=(time.perf_counter() - start) * 1000,
            detail=f"{type(e).__name__}: {e}",
        )
    ms = (time.perf_counter() - start) * 1000
    if resp.status_code != 200:
        body = resp.text[:200].replace("\n", " ")
        return Probe(False, resp.status_code, None, ms, body)
    data = resp.json()
    return Probe(
        ok=True,
        status=200,
        kind=data.get("kind"),
        latency_ms=ms,
        question=question,
        detail=f"citations={len(data.get('citations') or [])} cache_hit={data.get('cache_hit')}",
    )


def wait_for_recovery(deadline_s: float = 120.0) -> tuple[Probe | None, float | None]:
    """Time from dependency restart to the first fully healthy answer.

    This is the number an on-call engineer needs and the one nobody measures: bringing the
    dependency back is not the same as the service being well again.
    """
    start = time.perf_counter()
    while time.perf_counter() - start < deadline_s:
        p = probe()
        if p.ok and p.kind in ("grounded", "no_answer"):
            return p, time.perf_counter() - start
        time.sleep(2.0)
    return None, None


def flush_answer_cache(redis_container: str = "p5-medical-chatbot-redis-1") -> int:
    """Delete cached ANSWERS only — never FLUSHDB, never a volume.

    Required for correctness of the drill, not tidiness. The question pool restarts with
    each process, so by the second drill run the early questions are already cached and
    every probe is a cache hit — which is how this harness twice reported that Qdrant
    could be stopped with no effect. A cache hit exercises neither retrieval nor the model,
    so a drill that lands on one measures nothing and reports success.
    """
    code, out = docker(
        "exec",
        redis_container,
        "sh",
        "-c",
        "redis-cli --scan --pattern '*:ans:*' | xargs -r redis-cli del",
    )
    if code != 0:
        print(f"  (cache flush skipped: {out.splitlines()[0] if out else 'unavailable'})")
        return 0
    return int(out.strip() or 0) if out.strip().isdigit() else 0


def run_drill(name: str, container: str, *, probes: int = 3) -> DrillResult:
    res = DrillResult(name=name, container=container)

    # Flush BEFORE stopping anything: during a Redis outage the flush itself cannot run,
    # and after the outage the cache is cold anyway.
    flush_answer_cache()

    res.steady = probe()
    print(f"  steady:    {_fmt(res.steady)}")

    code, out = docker("stop", container)
    if code != 0:
        res.notes.append(f"could not stop {container}: {out}")
        print(f"  !! stop failed: {out}")
        return res
    print(f"  stopped {container}")

    for i in range(probes):
        p = probe()
        res.during.append(p)
        print(f"  during[{i}]: {_fmt(p)}")
        if "cache_hit=True" in p.detail and name != "redis":
            res.notes.append(
                f"probe {i} was a CACHE HIT — it did not exercise {name}; result not meaningful"
            )

    code, out = docker("start", container)
    if code != 0:
        res.notes.append(f"could not restart {container}: {out}")
        print(f"  !! RESTART FAILED: {out}")
        return res
    print(f"  restarted {container}; waiting for recovery...")

    res.recovered, res.recovery_seconds = wait_for_recovery()
    if res.recovered:
        print(f"  recovered in {res.recovery_seconds:.1f}s: {_fmt(res.recovered)}")
    else:
        res.notes.append("did NOT recover within 120s")
        print("  !! did not recover within 120s")
    return res


def _fmt(p: Probe) -> str:
    return f"status={p.status} kind={p.kind} {p.latency_ms:7.0f}ms {p.detail}"


def main() -> int:
    ap = argparse.ArgumentParser(description="P5.3 chaos drills (stop/start only)")
    ap.add_argument(
        "--targets",
        default="redis,qdrant,postgres,provider",
        help="comma-separated: redis, qdrant, postgres, provider",
    )
    ap.add_argument("--out", default="eval-reports/chaos.json")
    args = ap.parse_args()

    containers = {
        "redis": "p5-medical-chatbot-redis-1",
        "qdrant": "p5-medical-chatbot-qdrant-1",
        "postgres": "p5-medical-chatbot-postgres-1",
        "provider": "sglang-local",
    }

    warm = probe()
    if not warm.ok:
        print(f"ABORT: baseline probe failed ({_fmt(warm)}). Start the API first.")
        return 2
    print(f"baseline healthy: {_fmt(warm)}\n")

    results: list[DrillResult] = []
    for target in [t.strip() for t in args.targets.split(",") if t.strip()]:
        if target not in containers:
            print(f"skipping unknown target {target!r}")
            continue
        print(f"=== DRILL: {target} ===")
        results.append(run_drill(target, containers[target]))
        print()

    payload: list[dict[str, Any]] = [
        {
            "name": r.name,
            "container": r.container,
            "steady": vars(r.steady) if r.steady else None,
            "during": [vars(p) for p in r.during],
            "recovered": vars(r.recovered) if r.recovered else None,
            "recovery_seconds": r.recovery_seconds,
            "notes": r.notes,
        }
        for r in results
    ]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"wrote {args.out}")

    # What counts as passing.
    #
    #   200  answered, degraded or not          -> designed
    #   503  service-degraded / retrieval-down  -> designed: a TYPED, retryable refusal
    #   429  quota                              -> designed
    #   500  "unexpected error"                 -> FAIL: nobody anticipated this
    #     0  transport failure / no response    -> FAIL
    #
    # The 500-vs-503 line is the whole point. Both are "the request did not succeed", but
    # 503 means a dependency is down and the client should retry, while 500 means we have a
    # bug. Conflating them makes the bug-rate alert fire on every dependency blip and hides
    # real bugs inside outage noise. The first run of this drill called the provider outage
    # a failure because it returned 503 — the criterion was wrong, not the system.
    ACCEPTABLE = {200, 429, 503}
    failures = [
        r.name
        for r in results
        if any(p.status not in ACCEPTABLE for p in r.during) or r.recovered is None
    ]
    if failures:
        print(f"\nDRILLS WITH HARD FAILURES: {', '.join(failures)}")
        return 1
    print("\nall drills degraded gracefully and recovered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
