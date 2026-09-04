# Round 7 — multi-turn and conversation state

Every previous round asked one question at a time. Real use is a conversation, and that
introduces a stage none of the earlier rounds exercised: **condense**, which rewrites
*"What causes it?"* into something retrieval can actually search for.

This round drives real multi-turn sessions with a cookie jar and watches what the extra stage
does — including where it stops working.

> **Instrument reference:** Parts 0–4 of [INSPECTION_ROUND3.md](INSPECTION_ROUND3.md).

```bash
J=/tmp/cj.txt && rm -f $J        # a cookie jar IS the conversation
make cache-clear
```

Every request below uses `curl -c $J -b $J`. Without the jar each turn is a new anonymous
session and there is no history to condense from — which is itself a test, see Q3.

---

## Why condense exists

Retrieval searches for text. "What causes it?" contains no searchable noun — embedding it
produces a vector pointing at nothing in particular. So before retrieval, the pipeline
rewrites the question using the conversation so far.

It is **gated on cheap signals** — a pronoun, or a question of three words or fewer —
precisely so that first questions never pay for a model round-trip they cannot use.

```
turn 1  "What is pneumonia?"    no pronoun, 3+ words  →  condense SKIPPED   (0 ms)
turn 2  "What causes it?"       pronoun               →  condense RUNS    (249 ms)
```

---

## Q1 — The gate does not fire on a first question

> **What is pneumonia?**

Measured: `grounded`, 4 citations, **`condense_ms = 0`**.

### Prometheus
```promql
medbot_stage_duration_seconds_count{stage="condense"}    UNCHANGED
```

### Jaeger
The `condense` span is present but **zero-duration** — the stage ran, the gate declined to
call a model. Seeing a *real* duration here on a first turn means the gate is too loose and
you are paying for a rewrite that has no history to use.

### Grafana
**Stage latency p95** (row 3) — the `condense` line stays flat.

---

## Q2 — The pronoun follow-up (the one that matters)

> Turn 1: **What is pneumonia?**
> Turn 2: **What causes it?**

Measured: `grounded`, 4 citations, **`condense_ms = 249`**, and the answer correctly resolves
*it*:

> *"Pneumonia can be caused by bacteria, viruses, or other organisms…"*

### Prometheus
```promql
medbot_stage_duration_seconds_count{stage="condense"}    +1
medbot_stage_duration_seconds_sum{stage="condense"}      +0.249
```

### Grafana
**Stage latency p95** grows a **fifth line**. Until you run a follow-up, that panel has four
stages; `condense` only appears once multi-turn is exercised. An empty `condense` line does
not mean the feature is broken — it means nobody has had a conversation.

### Jaeger — the proof
**The `condense` span with a real duration IS the evidence multi-turn works.** It is the only
externally visible sign that history reached the pipeline. If it is absent on a follow-up,
history is not being loaded — which was a real bug.

### Langfuse — the subtle and important one
The trace input shows **what you typed**:

```json
{"question": "What causes it?", "n_contexts": 4}
```

**Not the rewrite.** Only the *retrieval query* is condensed; `state.question` is never
overwritten. If Langfuse ever showed the rewritten text here, the system would be putting its
own words in the user's mouth — corrupting the transcript, the trace, and the history that
feeds the next turn's condense.

### Postgres
```sql
select count(*) from messages;    -- grows by 2 per turn (your question + the answer)
```

---

## Q3 — The negative control: a pronoun with no history

> **What causes it?** — first message of a brand-new session

Measured: **`no_answer`**, `condense_ms = 0`, 0 citations.

This is correct and worth seeing. With no history, "it" is unresolvable, so the system
**declines rather than guessing**. A system that invented a topic here would be far worse than
one that shrugs.

### Grafana
**Answers by kind** — `no_answer` rises. **Declines by path** — this is a `retrieval_gate`
decline, the free one.

---

## Q4 — Topic switch

> Turn 3: **And what about asthma?**

Measured: `grounded`, **`condense_ms = 0`**, and the answer is about asthma.

The gate did not fire — four words, no pronoun — and it did not need to. The question already
contains a searchable noun. **The gate is economical rather than clever**, and here that is
exactly right.

---

## Q5 — Pronoun AFTER a topic switch (the failure)

> Turn 1: **What is pneumonia?**
> Turn 2: **And what about asthma?**
> Turn 3: **How is it treated?**

"it" should now mean **asthma**. Five clean runs, cache cleared, fresh session each time:

| run | result |
|---|---|
| 1 | wrong topic — answered about **eosinophilic pneumonia** |
| 2 | `no_answer` — declined |
| 3 | `no_answer` — declined |
| 4 | **asthma — correct** |
| 5 | `no_answer` — declined |

**1 correct out of 5.** `condense` fired every time (~290–340 ms), so the stage ran; it simply
did not reliably resolve the pronoun to the *most recent* topic.

### Why this is the most useful finding in the round

- **Every dashboard stays green.** Three of those runs are ordinary `no_answer`s and one is an
  ordinary `grounded` — Prometheus cannot tell that the grounded one was about the wrong
  disease.
- **A single-run test would pass or fail at random.** Run 4 alone would have "proved" this
  works.
- The one *wrong-topic* run is the dangerous outcome: a confident, cited, well-formed answer
  about the wrong condition. It is worse than the three declines.

### How to see it yourself
```bash
for r in 1 2 3; do
  J=/tmp/cj$r.txt; rm -f $J; make cache-clear >/dev/null
  for q in "What is pneumonia?" "And what about asthma?" "How is it treated?"; do
    curl -s -c $J -b $J -X POST localhost:5007/api/v1/query \
      -H 'content-type: application/json' \
      -d "{\"question\":\"$q\",\"stream\":false}" | grep -o '"kind":"[^"]*"'
  done
done
```

### Langfuse — where to diagnose it
This is the exact situation Langfuse exists for. Open the turn-3 trace and read
`input.n_contexts` and the retrieved passages:

- passages about **pneumonia** → condense rewrote the pronoun to the wrong topic; the fault is
  in the rewrite, before retrieval ever ran;
- passages about **asthma** but the answer declined → the rewrite was right and the *model*
  abstained.

**Those two failures look identical from outside and need opposite fixes.** Only Langfuse
distinguishes them, because only Langfuse keeps the contexts.

### Jaeger
`condense` present with real duration on all five runs. **The stage running is not the same as
the stage working** — a trap worth internalising: a span proves execution, never correctness.

---

## Q6 — History is a convenience, never a precondition

Delete the conversation mid-session and keep asking.

```bash
curl -s -X DELETE localhost:5007/api/v1/conversations/<id>
```

The next question must still answer. History is a D21 *degradation* concern: losing it costs
context, not availability.

### Grafana
**Errors by type** (row 4) — watch for `conversation-not-found` with `degradable=false`.
A burst of those after a delete is the UI re-fetching a thread it just destroyed; it is a
client bug, not a server fault, and it inflates your error rate against nothing.

---

## What to conclude

1. **The condense gate is well-tuned in the cheap direction.** It skips first questions and
   explicit topic switches, and fires on pronouns. No wasted model calls observed.
2. **Pronoun resolution across a topic switch is unreliable — 1 in 5.** The stage runs; the
   rewrite is not dependable.
3. **The dangerous outcome is not the decline, it is the confident wrong topic.** One run in
   five produced a cited answer about the wrong disease.
4. **A span proves a stage ran, never that it was right.** `condense_ms = 290` looked healthy
   in all five runs, including the four that failed.
5. **Langfuse is the only tool that can localise this**, because the question is *what did the
   rewrite retrieve* — content, not timing.

```bash
python scripts/inspect_stack.py
```
