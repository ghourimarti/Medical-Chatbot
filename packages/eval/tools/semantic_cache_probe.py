"""S19.4 — does a semantic cache clear D10's double guard? (go/no-go evidence)

D10 says the semantic cache stays OFF until it demonstrates ZERO false hits on the golden
set. This script produces that evidence, and deliberately runs THREE experiments, because
"zero false hits" on its own is not a decision — a cache that never fires also never fires
wrongly, and would pass D10's literal bar while being worthless:

  A. GOLDEN-SET SCAN — every pair of the 215 golden questions, embedded exactly as
     production embeds a query. Measures how often distinct questions collide above the
     threshold. This is D10's stated bar, and the weakest of the three: the golden set is
     deliberately DIVERSE, so it under-samples precisely the near-duplicate region a cache
     lives in.

  B. ADVERSARIAL MINIMAL PAIRS — hand-authored pairs differing by one clinically decisive
     token (adult/child, start/stop, hyper/hypo, max/min). Establishes the CEILING on
     dangerous similarity: the point above which a hit returns a confidently wrong medical
     answer.

  C. PARAPHRASE PAIRS — same intent, same correct answer, different wording. Establishes
     the FLOOR on useful similarity. Without it there is no way to tell a safe threshold
     from an inert one.

The decision is whether (B)'s ceiling and (C)'s floor leave a usable gap between them.

Offline: bge-large-en-v1.5 from the local HF cache. No API spend, no Qdrant required.

    uv run python packages/eval/tools/semantic_cache_probe.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from medeval.dataset import load_cases
from medeval.paths import DATASETS_DIR

# Must match production exactly, or the measurement describes a system we do not ship.
# apps/ml-service/src/medml/backends.py::QUERY_INSTRUCTION
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
MODEL_ID = "BAAI/bge-large-en-v1.5"

# Threshold under evaluation (medcore.config.Settings.semantic_cache_threshold), plus the
# neighbourhood, because "is 0.97 safe" is far less useful than "is ANY threshold safe".
THRESHOLDS = (0.95, 0.97, 0.98, 0.99, 0.995)

# Each pair differs by one clinically decisive token. A cache hit across any of these
# returns a confidently wrong answer to a medical question — the failure mode D10 names.
ADVERSARIAL_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("What is the aspirin dose for an adult?",
     "What is the aspirin dose for a child?", "adult/child"),
    ("What is the paracetamol dosage for an adult?",
     "What is the paracetamol dosage for an infant?", "adult/infant"),
    ("Should I start taking warfarin?",
     "Should I stop taking warfarin?", "start/stop"),
    ("What are the symptoms of hypoglycemia?",
     "What are the symptoms of hyperglycemia?", "hypo/hyper"),
    ("What causes hypertension?",
     "What causes hypotension?", "hyper/hypo"),
    ("What is the treatment for type 1 diabetes?",
     "What is the treatment for type 2 diabetes?", "type 1/type 2"),
    ("How is bacterial meningitis treated?",
     "How is viral meningitis treated?", "bacterial/viral"),
    ("Is ibuprofen safe during pregnancy?",
     "Is ibuprofen safe while breastfeeding?", "pregnancy/breastfeeding"),
    ("Can I take this medication with alcohol?",
     "Can I take this medication without alcohol?", "with/without"),
    ("What are the side effects of taking prednisone?",
     "What are the side effects of stopping prednisone?", "taking/stopping"),
    ("What is the maximum daily dose of ibuprofen?",
     "What is the minimum daily dose of ibuprofen?", "maximum/minimum"),
    ("Is this rash contagious?",
     "Is this rash cancerous?", "contagious/cancerous"),
    ("What should I do if I miss a dose?",
     "What should I do if I double a dose?", "miss/double"),
    ("How long should I take antibiotics for?",
     "How often should I take antibiotics?", "how long/how often"),
    ("What are the risks of surgery for this condition?",
     "What are the benefits of surgery for this condition?", "risks/benefits"),
)


# Experiment C. Same intent, different wording, SAME correct answer — the traffic a
# semantic cache exists to catch. Without this, a "zero false hits" result is meaningless:
# a cache that never fires also never fires wrongly. Deliberately excludes pure
# case/punctuation variants, which `normalize_question` already collapses for free in the
# exact-match ResponseCache — those would flatter the semantic layer with hits it does not
# earn. Topics are drawn from the A-D corpus the demo actually ingests.
PARAPHRASE_PAIRS: tuple[tuple[str, str], ...] = (
    ("What is an abscess?", "Can you explain what an abscess is?"),
    ("What causes chickenpox?", "What is the cause of chickenpox?"),
    ("What are the symptoms of cirrhosis?", "What symptoms does cirrhosis cause?"),
    ("How is conjunctivitis treated?", "What is the treatment for conjunctivitis?"),
    ("What is dementia?", "Could you define dementia for me?"),
    ("What causes a cold sore?", "What brings on a cold sore?"),
    ("What are the signs of dehydration?", "How can you tell if someone is dehydrated?"),
    ("What is celiac disease?", "Tell me about celiac disease."),
    ("How is croup diagnosed?", "What is the diagnostic process for croup?"),
    ("What is the prognosis for cystic fibrosis?",
     "What is the long-term outlook for someone with cystic fibrosis?"),
    ("What is diphtheria?", "What does diphtheria mean?"),
    ("What are the complications of diabetes mellitus?",
     "What problems can diabetes mellitus lead to?"),
)


def embed(texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_ID)
    prepared = [QUERY_INSTRUCTION + t for t in texts]
    vecs = model.encode(prepared, normalize_embeddings=True, batch_size=16,
                        show_progress_bar=True)
    return np.asarray(vecs, dtype=np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=DATASETS_DIR / "golden_core_v2.jsonl")
    ap.add_argument("--out", type=Path, default=Path("eval-reports/semantic-cache-probe.json"))
    args = ap.parse_args()

    cases = load_cases(args.dataset)
    questions = [c.question for c in cases]
    print(f"embedding {len(questions)} golden questions + "
          f"{2 * len(ADVERSARIAL_PAIRS)} adversarial probes with {MODEL_ID}\n")

    adv_flat = [q for a, b, _ in ADVERSARIAL_PAIRS for q in (a, b)]
    par_flat = [q for a, b in PARAPHRASE_PAIRS for q in (a, b)]
    vectors = embed(questions + adv_flat + par_flat)
    golden_vecs = vectors[: len(questions)]
    adv_vecs = vectors[len(questions):len(questions) + len(adv_flat)]
    par_vecs = vectors[len(questions) + len(adv_flat):]

    report: dict[str, object] = {"model": MODEL_ID, "n_golden": len(questions)}

    # --- A. golden-set pairwise scan --------------------------------------------------
    sims = golden_vecs @ golden_vecs.T
    iu = np.triu_indices(len(questions), k=1)
    pair_sims = sims[iu]
    print(f"\n=== A. golden-set scan — {len(pair_sims):,} pairs ===")
    print(f"  max pair similarity : {pair_sims.max():.4f}")
    print(f"  mean                : {pair_sims.mean():.4f}")
    print(f"  99.9th percentile   : {np.percentile(pair_sims, 99.9):.4f}")

    counts = {}
    for t in THRESHOLDS:
        n = int((pair_sims >= t).sum())
        counts[str(t)] = n
        print(f"  pairs >= {t:<5} : {n}")
    report["golden_pairs_above"] = counts
    report["golden_max_sim"] = float(pair_sims.max())

    collisions = []
    for i, j in zip(*iu, strict=True):
        s = float(sims[i, j])
        if s >= min(THRESHOLDS):
            a, b = cases[i], cases[j]
            same = (a.ground_truth or "") == (b.ground_truth or "")
            collisions.append({"a": a.id, "b": b.id, "sim": round(s, 4),
                               "same_ground_truth": same,
                               "qa": a.question, "qb": b.question})
    collisions.sort(key=lambda c: -c["sim"])  # type: ignore[arg-type,return-value]
    report["golden_collisions"] = collisions[:40]
    if collisions:
        print(f"\n  top collisions (>= {min(THRESHOLDS)}):")
        for c in collisions[:10]:
            flag = "SAME ANSWER" if c["same_ground_truth"] else "*** DIFFERENT ANSWER ***"
            print(f"    {c['sim']:.4f} {c['a']}/{c['b']} {flag}")
            print(f"        A: {c['qa'][:74]}")
            print(f"        B: {c['qb'][:74]}")
    else:
        print(f"\n  no golden pair reaches {min(THRESHOLDS)}")

    # --- B. adversarial minimal pairs -------------------------------------------------
    print(f"\n=== B. adversarial minimal pairs — {len(ADVERSARIAL_PAIRS)} pairs ===")
    print(f"  {'sim':>7}  {'>=0.97?':<9} distinction")
    adv_rows = []
    for k, (qa_, qb_, label) in enumerate(ADVERSARIAL_PAIRS):
        va, vb = adv_vecs[2 * k], adv_vecs[2 * k + 1]
        s = float(va @ vb)
        would_hit = s >= 0.97
        adv_rows.append({"a": qa_, "b": qb_, "distinction": label,
                         "sim": round(s, 4), "false_hit_at_0.97": would_hit})
        mark = "*** HIT ***" if would_hit else "miss"
        print(f"  {s:7.4f}  {mark:<9} {label}")
    report["adversarial"] = adv_rows

    n_hit = sum(1 for r in adv_rows if r["false_hit_at_0.97"])
    adv_sims = np.array([r["sim"] for r in adv_rows], dtype=np.float32)
    print(f"\n  false hits at 0.97 : {n_hit}/{len(adv_rows)}")
    worst = adv_rows[int(adv_sims.argmax())]["distinction"]
    print(f"  max adversarial sim: {adv_sims.max():.4f}  ({worst})")
    for t in THRESHOLDS:
        print(f"  would be unsafe at {t:<6}: {int((adv_sims >= t).sum())}/{len(adv_rows)} pairs")
    report["adversarial_false_hits_at_0.97"] = n_hit
    report["adversarial_max_sim"] = float(adv_sims.max())

    # --- C. paraphrases: would the cache ever actually fire? --------------------------
    print(f"\n=== C. paraphrase pairs (same answer expected) — {len(PARAPHRASE_PAIRS)} pairs ===")
    par_rows = []
    for k, (qa_, qb_) in enumerate(PARAPHRASE_PAIRS):
        s_ = float(par_vecs[2 * k] @ par_vecs[2 * k + 1])
        par_rows.append({"a": qa_, "b": qb_, "sim": round(s_, 4), "hit_at_0.97": s_ >= 0.97})
        print(f"  {s_:7.4f}  {'HIT' if s_ >= 0.97 else 'miss':<5} {qa_[:60]}")
    par_sims = np.array([r["sim"] for r in par_rows], dtype=np.float32)
    report["paraphrase"] = par_rows
    print(f"\n  max paraphrase sim : {par_sims.max():.4f}")
    print(f"  mean               : {par_sims.mean():.4f}")
    for t in THRESHOLDS:
        print(f"  would HIT at {t:<6}: {int((par_sims >= t).sum())}/{len(par_rows)} pairs")

    # --- the decision: is there a threshold that is both safe AND useful? --------------
    print("\n=== DECISION BAND ===")
    print(f"  highest DANGEROUS pair (adversarial) : {adv_sims.max():.4f}")
    print(f"  highest USEFUL pair (paraphrase)     : {par_sims.max():.4f}")
    if par_sims.max() > adv_sims.max():
        lo, hi = float(adv_sims.max()), float(par_sims.max())
        n_useful = int((par_sims > lo).sum())
        print(f"  -> a safe-and-useful window EXISTS: ({lo:.4f}, {hi:.4f}]")
        print(f"     it would catch {n_useful}/{len(par_rows)} paraphrases with 0 false hits")
    else:
        print("  -> NO safe-and-useful window: every threshold that catches a paraphrase")
        print("     also admits a clinically dangerous pair.")
    report["decision_band"] = {
        "max_dangerous": float(adv_sims.max()),
        "max_useful": float(par_sims.max()),
        "window_exists": bool(par_sims.max() > adv_sims.max()),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
