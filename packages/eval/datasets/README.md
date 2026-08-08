# Golden sets — provenance & curation policy

These datasets are the **evaluation product** (Decision 19). They are versioned as code and
reviewed like code. Changing a case changes what "good" means, so changes go through PR.

## Files
| File | Cases | Purpose |
|---|---|---|
| `golden_seed_v0.jsonl` | 10 | Plumbing seed — proves the harness runs. Not used for reporting. |
| `golden_core_v1.jsonl` | 90 | The baseline/regression set: **60 qa / 20 safety / 10 ooc**. |

## Stratification (golden_core_v1)
- **qa (60):** definition / description / cause / symptom / treatment / prognosis / detail questions,
  spread across ~25 conditions from the corpus (chickenpox, cirrhosis, conjunctivitis, dementia,
  cancer, celiac, croup, diphtheria, cystic fibrosis, colic, constipation, depression, carpal
  tunnel, concussion, cough, dehydration, dermatitis, Down syndrome, dyslexia, endometriosis,
  botulism, anemia, diabetes mellitus, cold sore).
- **safety (20):** personal diagnosis, dosage, prescription, emergency, crisis, medication
  management, and one prompt-injection framing — all must **refuse and redirect**.
- **ooc (10):** topics **verified absent** from the corpus (COVID-19, CRISPR, Zika, monkeypox,
  semaglutide, mRNA vaccines, GLP-1, ketamine therapy, vaping, West Nile) — all must **say
  they don't know / not in the provided information**, never confabulate.

## Grounding policy (the anti-hallucination discipline)
- Every `qa` `ground_truth` is grounded in the **Gale Encyclopedia of Medicine, 2nd ed.** —
  the exact corpus `demo/` ingests (`demo/data/The_GALE_ENCYCLOPEDIA_of_MEDICINE_SECOND.pdf`).
- Ground truths were written from **text extracted from the PDF** (see
  `packages/eval/tools/find_definitions.py` and `extract_corpus.py`), not from model memory.
  This matters: synthetic ground truth inherits a model's blind spots; corpus-grounded truth
  measures the system against the source of record.
- `ooc` absence was **verified programmatically** (substring scan over the extracted page text).
- The demo PDF is a **759-page volume** skewed to A–D topics; the golden set reflects that
  coverage deliberately (no questions about topics the corpus can't answer).

## Regeneration
```
uv run python packages/eval/tools/extract_corpus.py --build-cache   # rebuild page cache (gitignored)
uv run python packages/eval/tools/find_definitions.py Asthma Cirrhosis ...
uv run medeval validate packages/eval/datasets/golden_core_v1.jsonl
```

## Roadmap
Grows to ~215 cases in S19 (150 qa / 50 safety / 15 ooc) with judge calibration against human
labels. `v1` is the S1 baseline set — enough to measure the demo honestly and gate the S6 refactor.
