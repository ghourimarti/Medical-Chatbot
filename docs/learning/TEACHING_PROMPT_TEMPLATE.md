# Teaching-Transfer Prompt Template

> **Purpose.** After any step or phase of the P5 transformation completes, fork that session and paste
> the prompt below. It turns "Claude built this" into "here is how *you* rebuild it from an empty
> folder, and why every choice was made." The output is a single self-contained lesson you follow by
> hand in a scratch folder — the knowledge transfer, not just the artifact.
>
> **How to use:** copy everything in the fenced block, replace the `{{...}}` placeholders (a filled
> example for S1 is at the bottom), paste into the forked session. Optional flags are listed after
> the prompt.

---

## THE PROMPT (copy from here)

```
ROLE
You are the senior engineer who just implemented {{SCOPE}} in this project, now acting as my
teacher. I am rebuilding this project myself, from an empty folder, to internalize it. Your job is
knowledge transfer: the how, the why, the what-order, and the what-goes-wrong — not a summary.

SCOPE OF THIS LESSON
- Scope: {{SCOPE}} — {{SCOPE_NAME}}
- Implements: {{DECISIONS}}   (see docs/DECISION_LOG_V2.md, v2.1 locked)
- Plan reference: docs/TRANSFORMATION_PLAN.md
- I will re-create this in a SEPARATE practice folder. Assume I start with nothing but the demo/
  reference corpus and the docs. Do not assume any file from this repo already exists on my side.

OUTPUT CONTRACT — read this fully before writing anything
1. Produce the ENTIRE lesson in ONE response. Do not pause for my approval, do not ask clarifying
   questions, do not stop between sections. I am optimizing for token cost, so no back-and-forth.
2. ALSO save the identical content to `{{OUT_PATH}}` using the Write tool. The file is the source of
   truth if the chat output gets truncated.
3. If the content would exceed one response, continue immediately in a second message, picking up
   exactly where you left off — never re-print what you already wrote, never summarize instead of
   finishing.
4. This session is READ-ONLY on project code. Do not modify, refactor, or "improve" any project file.
   The only file you write is the lesson at `{{OUT_PATH}}`. Do not run git.
5. Fidelity rule — this is the most important instruction: teach what ACTUALLY happened in the
   session being forked. Real commands, real file contents, real outputs, real errors, real
   corrections. Do NOT invent a cleaner history. If something was discovered by trial and error, say
   so and show the trial. If you are unsure whether a detail actually occurred, mark it
   `[reconstructed]` rather than presenting it as history.

REQUIRED SECTIONS, IN THIS ORDER

§0. LEARNING TODO LIST (first thing in the response)
   A numbered checklist of the learning sub-steps I will follow, in execution order, each phrased as
   an action I perform ("Create schema.py and make its 5 tests pass"). Include a time estimate per
   item and a total. Also emit it via the TodoWrite tool so it renders as a live checklist.

§1. WHAT THIS STEP IS AND WHY IT EXISTS
   - In plain language: what this step delivers and what becomes possible after it.
   - The Decision Log entries it implements and the specific Phase-1 NFR numbers it serves — quote
     the numbers (RPS, latency, SLO, cost, thresholds), don't paraphrase them.
   - What would break later if this step were skipped or done after the next one.

§2. PREREQUISITES AND ENVIRONMENT
   - Exact tool versions actually in use (Python, uv, OS/shell, any service versions).
   - Environment variables and secret files needed, where they go, and how they are kept out of git.
   - Any external asset required (corpus PDF, model download, container image) and its size.
   - The one-time setup commands, with expected output.

§3. THE MENTAL MODEL (before any code)
   - How a senior decides the BUILD ORDER for this step: horizontal layers vs vertical slice, what
     gets created before business logic, and why.
   - The decision gates inside this step — points where a choice must be frozen before the next file
     can be written, and what it costs to change later.
   - The 2–4 sentence "shape" of the step someone should be able to recite from memory.

§4. THE ORDERED BUILD SEQUENCE — the core of the lesson
   For EVERY file created or modified, in the exact order it should be created, give a block:

   #N  path/to/file
   - Purpose: one line.
   - Why at this position: what must exist before it; what depends on it after.
   - Type: scaffolding / config / domain-logic / data / test / tooling.
   - Implements: Decision or NFR reference, if any.
   - FULL FILE CONTENT: the complete final code in a fenced block — not a diff, not an excerpt, not
     "…rest unchanged". I am retyping this by hand.
   - Line-by-line commentary on the non-obvious parts only: every design choice a reader would
     otherwise copy without understanding. Explain WHY that line is that way, and what a naive
     alternative would have cost.
   - Verify it works: the exact command to prove this file is correct before moving on, with the
     expected output.
   - Junior trap: the specific mistake a less experienced dev makes at this file, and its symptom.

   Interleave dependency installs at the exact position they become necessary — show the command,
   what it pulls in, and why it could not have been installed earlier or later.

§5. COMMAND LOG — every command, in order
   A single table or ordered list of every shell command run during the step: command, what it is
   for, expected output/exit condition, and what to do if it fails. Include the ones that failed and
   were retried differently.

§6. DEAD ENDS, ERRORS, AND CORRECTIONS (do not skip this — it is the highest-value section)
   Every wrong turn actually taken: what was tried, the real error message or bad result, the
   diagnosis, and the fix. Include version conflicts, API drift, bad heuristics, wrong assumptions
   about data. For each, state the general lesson so I recognize the pattern next time. If a
   quality gate (lint/type/test) failed and was fixed, show the failure and the fix.

§7. CONCEPT PRIMERS
   For every library, pattern, or term in this step that is new or advanced: a 5-minute primer —
   what it is, the mental model, the 3 API calls that matter, when to use it, when NOT to, and one
   line on why it was chosen over the obvious alternative. Go deeper on anything in my skill-gap
   list (evaluation, observability/SLOs, production Kubernetes, inference serving, AI security,
   distributed-systems and cost engineering); go lighter on things I already know from my course
   inventory (LangChain basics, Docker basics, Python, SQL).

§8. HOW TO KNOW IT WORKED — verification and Definition of Done
   - The step's Definition of Done, restated as a checklist I can tick.
   - Every verification command with its expected output, in the order I should run them.
   - What "subtly wrong but passing" looks like here — the failure mode that still goes green.

§9. CHECKPOINTS AND COMMITS
   Where a senior stops, runs everything, and commits — and WHY the boundary falls there. Give the
   exact `git add` scope and the conventional commit message for each checkpoint. Do not run git.

§10. SELF-TEST — prove I understood
   - 8–12 questions with answers hidden below (not inline), mixing recall ("what does X do"),
     reasoning ("why is Y created before Z"), and design ("what changes if the corpus is 100× bigger").
   - 2–3 small exercises that modify or extend what was built, with a hint and the expected result.
   - 3 "explain it to an interviewer" prompts: how I would describe this step's engineering judgment
     in 60 seconds, and the follow-up question a senior interviewer would ask next.

§11. REUSABLE VS PROJECT-SPECIFIC
   A short two-column list: which parts of this step are a portable pattern I should carry to every
   future project, and which are specific to this corpus/domain/stack. Name the pattern properly
   (e.g. "characterization test", "strangler fig", "cache-aside") so I can search for it later.

§12. THE BIG-PICTURE TABLE (end of the lesson)
   One table giving the whole step at a glance. Rows = the build sub-steps in order. Columns:
   | # | Sub-step name | File created/modified | Key functions/classes in that file (one sub-row per
   function: name → what it does → why it exists) | Type | Implements (Decision/NFR) | Verify command
   | Junior trap | Reusable or project-specific |
   Use sub-rows so every function in every file appears. After the table, add a 3-line "if you
   remember only three things from this step" summary.

STYLE RULES
- Teach the reasoning, never just the result. Every "do X" needs a "because Y".
- No filler, no motivational text, no re-explaining what I already did in earlier steps.
- Prefer tables and per-file blocks over prose paragraphs.
- Where two orderings were both defensible, say so and say which you would pick and why.
- Use exact numbers and exact file paths. Never write "some", "several", or "etc." where a number
  or a name belongs.
- Mark anything you are inferring rather than recalling with [reconstructed].

Begin with §0 now.
```

## (copy to here)

---

## Placeholders

| Placeholder | Meaning | Example |
|---|---|---|
| `{{SCOPE}}` | The exact step or phase completed | `Phase 4 · Step S1` or `Phase 2 (Architecture Decisions)` |
| `{{SCOPE_NAME}}` | Its title from the plan | `Eval harness + golden-90 + demo baseline` |
| `{{DECISIONS}}` | Decision Log refs implemented | `D19` / `D2, D5, D6, D7` |
| `{{OUT_PATH}}` | Where the lesson gets saved | `docs/learning/P4-S1-eval-harness-guide.md` |

Naming convention for `{{OUT_PATH}}`: `docs/learning/P<phase>-<step>-<slug>-guide.md`
(e.g. `P4-S3-thin-slice-guide.md`, `P2-decisions-guide.md`).

---

## Optional flags — append any of these to the prompt

| Flag text to append | Effect |
|---|---|
| `FLAG: file-only — write the lesson to {{OUT_PATH}} and reply in chat with only the §0 todo list and the §12 table.` | Roughly halves token cost. Use when you'll read the file anyway. |
| `FLAG: no-code-dump — reference file paths instead of pasting full contents for files longer than 80 lines.` | Use for later steps with big files, once you're comfortable reading from the repo. |
| `FLAG: deep-dive on <topic> — expand §7 for this topic into a full tutorial with runnable examples.` | For a gap you want to close hard (e.g. `RAGAS`, `KEDA`, `vLLM batching`). |
| `FLAG: from-zero — assume I have an empty machine; include OS-level setup (uv install, Docker, WSL2/GPU drivers).` | For steps that need new infrastructure (S3b, S13, S15). |
| `FLAG: compare-mine — I have already attempted this step; my files are at <path>. Add a §13 that diffs my attempt against the reference and grades it.` | Use *after* you build it yourself — the highest-learning mode. |

---

## Phase-level variant

Phases 1, 2, 3, 5, 6 are not file-creation work — the lesson must teach *decision sequencing*, not
code. When `{{SCOPE}}` is a phase, append this to the prompt:

```
PHASE-LEVEL ADAPTATION
This scope is a reasoning phase, not a coding step. Replace §4 (ordered file sequence) with:

§4-ALT. THE ORDERED DECISION/TASK SEQUENCE
   For each decision or task, in the order a senior works through it:
   - What is being decided/done, and the question it answers.
   - The full option space that was realistically on the table at our scale, not just the winner.
   - The inputs it required — which upstream decision or NFR had to exist first, and why it is
     impossible to answer this one before that one.
   - The chosen answer and the specific number or constraint that forced it.
   - What was given up, and the flip-trigger that would reverse it.
   - The junior trap at this decision.
   End with the dependency graph as ASCII, and a ranked list of which decisions deserved the most
   deliberation (by cost-of-reversal) versus which deserved a one-line flip-trigger.

Also adapt §12: rows = decisions/tasks; columns = number, name, options considered, pick, forcing
constraint, reversibility + flip-trigger, downstream decisions it unblocks, junior trap.
```

---

## Filled example — the S1 invocation

```
ROLE
You are the senior engineer who just implemented Phase 4 · Step S1 in this project, now acting as my
teacher. ...

SCOPE OF THIS LESSON
- Scope: Phase 4 · Step S1 — Eval harness + golden-90 + demo baseline
- Implements: D19 (evaluation strategy), with D22 (repo structure) and D20 (cost caps) touched
- Plan reference: docs/TRANSFORMATION_PLAN.md
...
- Save to: docs/learning/P4-S1-eval-harness-guide.md
```

For S1 specifically, make sure the lesson does not omit:
- the **characterization adapter** idea (measuring `demo/` without editing it — one flag flipped),
- the **corpus-grounding discipline** (ground truths extracted from the real PDF, out-of-corpus
  topics verified absent programmatically),
- the **meta-evaluation** of metrics (fixtures proving a bad answer scores below a good one),
- the **LangChain 1.x ↔ RAGAS 0.4 incompatibility** that was hit live and how it was diagnosed and
  pinned,
- the **page-heading heuristic that failed** during curation (page 344 looked like Appendicitis but
  contained Crohn's disease text) and what replaced it,
- the **keyless MockTarget** that lets CI verify the pipeline without a secret,
- why the **dataset is committed as an asset** while the harness code is disposable around it.

---

## Suggested workflow (how to actually learn from this)

1. **Fork** the session at the moment the step completed.
2. **Paste** the filled prompt. Read the lesson once, end to end, without typing anything.
3. **Close the lesson.** In your practice folder, try to rebuild the step from the §0 todo list and
   the §12 table alone.
4. **Get stuck**, then consult the per-file blocks — the sticking points are the actual learning.
5. Run the **§8 verification** commands; they must pass in your folder too.
6. Do the **§10 self-test** from memory. Anything you can't answer, re-read that file's commentary.
7. Optionally re-paste with `FLAG: compare-mine` to have your attempt graded against the reference.
8. Keep a running `docs/learning/NOTES.md` of your own — the traps you personally fell into. That
   file, not the guides, is what makes you fast on the next project.
