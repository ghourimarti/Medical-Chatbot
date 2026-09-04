# Container images — size, provenance, and the CUDA finding

## Measured sizes

| Image | Before (CUDA torch) | After (CPU torch) | Saving |
|---|---:|---:|---:|
| `medbot-api` | 8.84 GB | **2.32 GB** | −6.52 GB (−74%) |
| `medbot-ml` | 8.50 GB | **1.95 GB** | −6.55 GB (−77%) |
| `medbot-worker` | 8.84 GB | **2.32 GB** | −6.52 GB (−74%) |
| **total** | **26.18 GB** | **6.59 GB** | **−19.59 GB (−75%)** |

Rebuild: `make images` · Verify the lock stays clean: `uv run pytest packages/core/tests/test_lockfile_invariants.py`

## The finding: 3.4 GB estimated, 6.5 GB actual — per image

`sentence-transformers` pulls `torch`, and torch's default resolution on Linux drags in
**16 `nvidia-*` / `triton` / `cuda-toolkit` packages** to run CUDA kernels. Every service in
this workspace is CPU-only by design (D5 — bge-large and the cross-encoder run on CPU pods);
the GPU venues are separate vLLM/SGLang containers with their own images that are not
resolved from this lockfile. So the CUDA stack was pure dead weight in all three images.

Three details made it survive this long:

1. **It is invisible on Windows.** Those wheels are linux-only, so a `uv sync` on the dev
   machine never installs them. The weight exists *only* in the images — precisely where it
   is least observed and most expensive.
2. **A transitive dependency does not pick up a source override.** Adding
   `torch = { index = "pytorch-cpu" }` to `[tool.uv.sources]` changed nothing, because torch
   was only reached *through* `sentence-transformers`. The pin binds only where torch is a
   **declared** dependency, so it is now declared explicitly in `apps/api`,
   `apps/ml-service`, and `packages/eval` with a comment saying why.
3. **The saving is roughly double the estimate**, because removing CUDA also removes the
   `cuda-toolkit` extras, cudnn, nccl, cusparselt, nvshmem and triton — and the CPU torch
   wheel is itself far smaller than the CUDA one.

### Why it mattered beyond tidiness
Three images at ~8.8 GB is ~26 GB, which does not fit the ~14 GB of disk on a standard CI
runner — this was the recorded blocker on building and pushing images. At 6.6 GB total it
fits with room to spare.

### Verified after the change
```
torch 2.13.0+cpu · cuda available: False · sentence-transformers 5.6.0 · CPU matmul ok
find / -name 'libcud*' -o -name 'nvidia*'  ->  (no matches)
```

### Guard
`packages/core/tests/test_lockfile_invariants.py` fails if any `nvidia-*` / `triton` /
`cuda-*` package returns to `uv.lock`, and separately asserts torch still resolves from
`download.pytorch.org/whl/cpu` — the second check exists because absence of CUDA packages
could also mean torch vanished entirely. The guard was verified against a synthetic
regressed lock; a guard never seen failing is not a guard.

## Open finding — the API image still carries an ML stack it does not use

`medbot-api` at 2.32 GB still contains torch (750 MB), transformers, scipy, sympy, sklearn
and onnxruntime — roughly **1.15 GB** — for the in-process embedder/reranker fallback. In
every deployed configuration `ML_SERVICE_URL` is set, so the API calls `ml-service` over HTTP
and never loads a model.

D22 splits these services so "the API image stays slim". That split is real at *runtime* but
not at *dependency* level: `deps.py` imports `BgeEmbedder` eagerly, and `embedder.py` imports
`sentence_transformers` at module scope, so the package must be installed for the API to
start at all. `reranker.py` already imports it lazily inside the function — the two adapters
are inconsistent. Making the import lazy and the dependency an optional extra would remove
~1.15 GB and make the architecture's claim true.

## Image discipline
- Multi-stage: builder holds uv + compilers, runtime layer holds neither.
- Non-root: `appuser` uid 10001 in every image.
- `HEALTHCHECK` in every image; ml-service uses a longer `start_period` for model warmup.
- `.dockerignore` excludes `.env`, `.git`, `demo/vectorstore`, `demo/data`, `eval-reports`,
  `docs` — fixing demo's `COPY . .` which shipped 27 MB of artifacts into the image.

## Vulnerability scan — Trivy, HIGH + CRITICAL

Command (Git Bash):
```bash
mkdir -p security-reports
for s in api ml worker; do
  MSYS_NO_PATHCONV=1 docker run --rm -v //var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy:latest image --severity HIGH,CRITICAL --scanners vuln \
    --format table "medbot-$s:0.1.0" > "security-reports/trivy-$s.txt" 2>&1
done
```

| Image | OS (debian 13.6) | Python packages |
|---|---|---|
| api | 26 (22 HIGH, 4 CRITICAL) | 3 HIGH |
| ml | 26 (22 HIGH, 4 CRITICAL) | 2 HIGH |
| worker | 26 (22 HIGH, 4 CRITICAL) | 3 HIGH |

The OS counts are identical across all three because they are inherited wholesale from the
shared `python:3.13-slim` base — they are a property of the base image, not of our code.

### Triage — reachability, not counting

A count is not a risk assessment. Each finding was traced to a file inside the image and to
a call path in our code.

| Finding | Package | Where it actually lives | Ours? | Reachable? | Disposition |
|---|---|---|---|---|---|
| CVE-2026-34070 | `langchain-core` 0.3.86 | our venv | **yes** | **no** | Accept — see below |
| GHSA-6v7p-g79w-8964 | `msgpack` 1.1.2 | `pip/_vendor` (base image) | no | no | Removed by dropping pip |
| CVE-2025-47273 | `setuptools` 70.3.0 | `pip/_vendor` (base image) | no | no | Removed by dropping pip |
| CVE-2026-13221 | `perl-base` | base image OS | no | no | No upstream fix (`affected`) |

**CVE-2026-34070 (langchain-core) — accepted, with the reasoning recorded.**
The vulnerability is a path traversal in LangChain's *legacy* `load_prompt` helpers. We never
call it: the `load_prompt` in `apps/api/.../rag.py` is **our own** `medcore.prompts.load_prompt`,
which reads a fixed directory of versioned files and takes no caller-supplied path. Verified by
grep across `apps/` and `packages/`.

The fix requires `langchain-core >= 1.2.22`, i.e. LangChain 1.x — which **breaks ragas 0.4.3**,
our eval judge stack. That is measured, not assumed: LangChain 1.x removes
`langchain_community.chat_models.vertexai`, which `ragas.llms.base` imports at module scope, so
the whole eval harness fails to import. ragas 0.4.3 is already the latest release, so
the pin is forced from both ends. Revisit when ragas supports LangChain 1.x.

**The pip findings — fixed by removing the tool, not by upgrading it.**
`/usr/local/lib/python3.13/site-packages/` in these images contains exactly one thing: pip. Both
"vulnerable" packages are vendored *inside* it. Our own venv already ships setuptools 83.0.0,
well past the 78.1.1 fix — the flagged 70.3.0 was never a dependency of ours.

The runtime layer has no reason to install packages (uv resolves and installs in the builder
stage), so all three Dockerfiles now delete pip from the runtime image. That removes two
findings and the capability behind them: a container that *cannot* fetch and install packages
is a smaller target than one that merely *should not*. Apply with a rebuild.

### Residual risk, stated plainly
The 4 CRITICAL OS findings are inherited from `python:3.13-slim`, and the one sampled
(`perl-base` CVE-2026-13221) is marked `affected` — Debian has no fixed version published, so
there is nothing to upgrade to. Options are (a) wait for Debian, (b) move to a
distroless/Chainguard base, which would also remove `apt-get` and most of the
OS surface. That is the D15-listed alternative and is deferred, not dismissed: it is a base-image
migration with its own verification cost, and it belongs with the Phase 7/8 hardening work
rather than inside a local-validation phase.
