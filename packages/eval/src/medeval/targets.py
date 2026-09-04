"""Target adapters: the pipelines under evaluation, behind one protocol.

DemoTarget is a characterization adapter. It rebuilds the demo chain out of demo's own
components and changes only `return_source_documents`, so retrieved contexts become
observable without touching demo/ source. Demo config uses CWD-relative paths, so calls
are pinned to demo/ as the working directory rather than editing that trait away.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from dotenv import load_dotenv

from medeval.paths import DEMO_DIR, REPO_ROOT
from medeval.schema import TargetAnswer

_RETRYABLE_MARKERS = ("429", "rate limit", "rate_limit", "503", "overloaded", "timeout")
_MAX_ATTEMPTS = 4


class Target(Protocol):
    name: str

    def answer(self, question: str) -> TargetAnswer: ...


@contextmanager
def demo_cwd() -> Iterator[None]:
    prev = os.getcwd()
    os.chdir(DEMO_DIR)
    try:
        yield
    finally:
        os.chdir(prev)


class DemoTarget:
    name = "demo"

    def __init__(self) -> None:
        load_dotenv(REPO_ROOT / ".env")
        load_dotenv(DEMO_DIR / ".env")
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError(
                "GROQ_API_KEY is not set. Put it in <repo>/.env or demo/.env (both gitignored)."
            )
        if str(DEMO_DIR) not in sys.path:
            sys.path.insert(0, str(DEMO_DIR))
        with demo_cwd():
            from app.components.llm import load_llm  # demo's own loaders, unmodified
            from app.components.retriever import set_custom_prompt
            from app.components.vector_store import load_vector_store
            from langchain.chains import RetrievalQA

            db = load_vector_store()
            if db is None:
                raise RuntimeError("demo vector store failed to load (vectorstore/db_faiss)")
            llm = load_llm()
            if llm is None:
                raise RuntimeError("demo LLM failed to load (check GROQ_API_KEY)")
            self._chain: Any = RetrievalQA.from_chain_type(
                llm=llm,
                chain_type="stuff",
                retriever=db.as_retriever(search_kwargs={"k": 1}),
                return_source_documents=True,  # the ONE observability change vs demo
                chain_type_kwargs={"prompt": set_custom_prompt()},
            )
        self._model_id = "groq/llama-3.1-8b-instant"

    def answer(self, question: str) -> TargetAnswer:
        t0 = time.perf_counter()
        last_err: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                with demo_cwd():
                    out = self._chain.invoke({"query": question})
                return TargetAnswer(
                    answer=str(out.get("result", "")),
                    contexts=[d.page_content for d in out.get("source_documents", [])],
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    model_id=self._model_id,
                )
            except Exception as e:  # noqa: BLE001 (a baseline records failures, not dies)
                last_err = e
                msg = str(e).lower()
                if attempt < _MAX_ATTEMPTS - 1 and any(m in msg for m in _RETRYABLE_MARKERS):
                    time.sleep(2**attempt)
                    continue
                break
        return TargetAnswer(
            answer="",
            contexts=[],
            latency_ms=(time.perf_counter() - t0) * 1000,
            model_id=self._model_id,
            error=f"{type(last_err).__name__}: {last_err}",
        )


class MockTarget:
    """Deterministic, no-network target: proves the runner→score→report pipeline offline
    (CI smoke, and Protocol-B verification without a live API key). Emits category-plausible
    answers so deterministic metrics exercise all branches."""

    name = "mock"

    def answer(self, question: str) -> TargetAnswer:
        low = question.lower()
        if any(w in low for w in ("dose", "diagnose", "prescribe", "milligrams", "insulin")):
            text = "I can't provide personal medical advice; please consult a healthcare provider."
        elif any(w in low for w in ("covid", "crispr", "zika", "monkeypox", "vaping", "mrna")):
            text = "The provided context does not contain information on this topic."
        else:
            text = "Based on the context, this condition is described in the encyclopedia [1]."
        return TargetAnswer(
            answer=text, contexts=["mock context passage"], latency_ms=1.0, model_id="mock"
        )


class PipelineTarget:
    """The current stack: hybrid retrieval -> rerank -> threshold -> cited generation.

    Runs the real RagPipeline in-process against the real Qdrant, which is what makes the
    before/after delta measurable. Going through the deployed HTTP surface would add a
    server dependency to every eval run for no extra signal.
    """

    name = "pipeline"

    def __init__(self) -> None:
        load_dotenv(REPO_ROOT / ".env")
        from medapi.deps import build_services

        from medcore.config import get_settings

        self._services = build_services(get_settings())
        self._loop = asyncio.new_event_loop()
        self._loop.run_until_complete(self._services.store.ensure_collection())

    def answer(self, question: str) -> TargetAnswer:
        t0 = time.perf_counter()
        try:
            ans, contexts = self._loop.run_until_complete(
                self._services.pipeline.answer_verbose(question)
            )
        except Exception as e:  # noqa: BLE001 (a baseline records failures, not dies)
            return TargetAnswer(
                answer="",
                contexts=[],
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=f"{type(e).__name__}: {e}",
            )
        return TargetAnswer(
            answer=ans.text,
            contexts=contexts,  # full passage text: RAGAS scores what the model saw
            latency_ms=ans.timings.total_ms or (time.perf_counter() - t0) * 1000,
            model_id=ans.model_id,
        )


def get_target(name: str) -> Target:
    if name == "demo":
        return DemoTarget()
    if name == "mock":
        return MockTarget()
    if name == "pipeline":
        return PipelineTarget()
    raise ValueError(f"unknown target: {name!r} (available: demo, mock, pipeline)")
