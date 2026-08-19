# P5.1 — Security audit

> Reproduce: `make audit` · Date: 2026-08-17 · Scope: secrets, dependencies, attack surface

## 1. Secrets — CLEAN ✅

| Check | Method | Result |
|---|---|---|
| `.env` tracked by git | `git ls-files --error-unmatch .env` | ✅ never staged |
| `.env` in git **history** | `git log --all --full-history -- .env demo/.env` | ✅ never committed |
| Hardcoded key patterns | `git grep -E 'gsk_\|hf_\|sk-\|AKIA'` on tracked files | ✅ none |

The history check is the one that matters. A secret deleted from the working tree but
present in history is still compromised, and a `git grep` of HEAD would never see it.

## 2. Dependencies — 13 findings, 4 fixed, 9 assessed as NOT REACHABLE

### Fixed by upgrade
| Package | From | To | Issues |
|---|---|---|---|
| aiohttp | 3.14.1 | 3.14.3 | PYSEC-2026-3546, -3547 |
| pypdf | 6.14.2 | 6.16.1 | PYSEC-2026-3655, -3656 |

### Blocked by an upstream pin — and why that is acceptable

The remaining nine all live in the LangChain family, pinned to `0.3.x`. **The pin is not a
choice**: `ragas` 0.4.3 (the newest release) imports
`langchain_community.chat_models.vertexai`, which LangChain 1.x removed. Discovered in S1;
confirmed against PyPI in P5.1 that no newer ragas exists.

**Exploitability assessment — each CVE checked against actual code, not assumed:**

| Package | Issue | Vulnerable API | Used here? | Verdict |
|---|---|---|---|---|
| langchain | PYSEC-2026-2192 | file-search middleware, `load_prompt` config loaders, path-prefix authz | ❌ | **not reachable** |
| langchain-core | PYSEC-2026-2193 | `langchain_core.prompts.loading.load_prompt()` | ❌ | **not reachable** |
| langchain-core | PYSEC-2026-2562 | `ChatOpenAI.get_num_tokens_from_messages()` (image SSRF) | ❌ | **not reachable** |
| langchain-openai | PYSEC-2026-76 | `_url_to_size()` image fetch | ❌ | **not reachable** |
| langchain-text-splitters | PYSEC-2026-77 | `HTMLHeaderTextSplitter.split_text_from_url()` | ❌ | **not reachable** |
| ragas | PYSEC-2026-3046 | `multi_modal_faithfulness` SSRF | ❌ | **not reachable**, dev-only |
| diskcache | PYSEC-2026-2447 | pickle cache deserialisation | transitive (ragas) | **low** — requires prior host write access; dev-only |

Verified by search: `load_prompt`, `split_text_from_url`, `HTMLHeaderTextSplitter`,
`get_num_tokens_from_messages`, `multi_modal_faithfulness`, and `ChatOpenAI` appear
**nowhere** in this codebase.

What we actually use from LangChain is deliberately tiny:
- `langchain_core.runnables` — LCEL composition over our own functions (D6)
- `langchain_core.messages` — plain message types
- `RecursiveCharacterTextSplitter.split_text()` — on a **local** PDF, never `split_text_from_url`

**Every remaining CVE is an SSRF or path-traversal reachable only through APIs we do not
call.** That is an assessment, not a dismissal: if a future step adds vision input, HTML
splitting from URLs, or LangChain's prompt loaders, this verdict must be re-run.

**Remediation triggers (any one flips this from accepted to must-fix):**
1. ragas publishes a LangChain 1.x-compatible release → unpin immediately.
2. The API gains vision/image input → PYSEC-2026-2562 and -76 become reachable.
3. Ingestion gains URL-based HTML fetching → PYSEC-2026-77 becomes reachable.
4. A new CVE lands in `langchain_core.runnables` → no workaround; ragas must be dropped
   (D19 named DeepEval as the alternative).

## 3. Attack-surface reduction — dead code carrying dependencies

The audit's most useful output was not a CVE. Two modules were still present but no longer
reachable, and each dragged a dependency into the production image:

| Removed | Superseded by | Dependency dropped |
|---|---|---|
| `adapters/model.py` (`GroqModel`) | S13 `OpenAICompatModel` (raw httpx) | **langchain-groq**, tiktoken |
| `scripts/reindex.py` | S9 `medworker-ingest` (verify-then-swap) | — |

`reindex.py` also mutated the **live** collection, which S9 replaced precisely because that
lets readers observe a half-ingested corpus. Leaving it wired meant the unsafe path was
still one `make reindex` away. `make reindex` now calls the worker.

**The general lesson:** a dependency audit lists what you *have*; asking "what still calls
this?" tells you what you *need*. The second question deleted more attack surface than the
first.

## 4. Licenses

Runtime dependencies are Apache-2.0 / MIT / BSD (FastAPI, SQLAlchemy, Qdrant client,
sentence-transformers, structlog, prometheus-client, redis, boto3, httpx, pydantic).
No copyleft (GPL/AGPL) in the runtime path. Models: bge-large-en-v1.5 (MIT),
bge-reranker-base (MIT), Qwen2.5-7B-Instruct (Apache-2.0), Llama-3.1 (Meta Community
License — accepted via HF gating, redistribution restricted).

**Corpus caveat:** the Gale Encyclopedia of Medicine PDF is third-party copyrighted content
used here for local evaluation only. It is gitignored and must not be redistributed with
the project — a real constraint on publishing this portfolio piece.
