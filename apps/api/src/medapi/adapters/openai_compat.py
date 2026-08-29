"""One adapter for every serving venue (D4b, D12).

vLLM, SGLang, RunPod, AWS-hosted vLLM, and Groq all expose the SAME OpenAI-compatible
`/v1/chat/completions` API. So the multi-venue design does not need five adapters — it
needs one adapter with a configurable `base_url`. That is the entire reason D4b is cheap
to build: the protocol was already uniform, the seam (ModelPort, S2) was already there.

Uses raw httpx rather than the openai SDK deliberately: the SDK adds retry and timeout
behaviour we must control ourselves, because retries here interact with the circuit
breaker and the failover chain. Two layers of independent retry logic is how a provider
outage turns into a thundering herd.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence

import httpx

from medcore.errors import ProviderError
from medcore.schema import Completion, Message, Usage

logger = logging.getLogger("medapi.venue")


def _describe(e: Exception) -> str:
    """Render an httpx exception so the log identifies the failure.

    Found in P5.2: several httpx exceptions — ConnectError, ReadTimeout, RemoteProtocolError
    — carry an EMPTY str(). `f"{venue}: {e}"` therefore logged "local: " on every failure,
    which is indistinguishable between "nothing is listening", "the request timed out", and
    "the server hung up". Hours of a real incident are lost to that.

    The exception TYPE is always informative, so lead with it; for HTTP status errors the
    response body carries the provider's own explanation, which is the single most useful
    line available (SGLang, for instance, reports exact token counts on a 400).
    """
    detail = str(e).strip()
    if isinstance(e, httpx.HTTPStatusError):
        body = e.response.text[:300].replace("\n", " ").strip()
        return f"{type(e).__name__} status={e.response.status_code} body={body!r}"
    return f"{type(e).__name__}" + (f": {detail}" if detail else " (no message)")


class OpenAICompatModel:
    """ModelPort over any OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        venue: str,
        base_url: str,
        model_id: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.venue = venue
        self._model_id = model_id
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # A User-Agent is not optional: providers behind Cloudflare (Groq among them)
        # return 403 to requests without one — measured in S3b.
        headers["User-Agent"] = "medbot/0.1"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    def _payload(
        self, messages: Sequence[Message], max_tokens: int, temperature: float, stream: bool
    ) -> dict[str, object]:
        return {
            "model": self._model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        try:
            resp = await self._client.post(
                "/chat/completions",
                json=self._payload(messages, max_tokens, temperature, stream=False),
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.venue}: {_describe(e)}", cause=e) from e
        data = resp.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        return Completion(
            text=choice["message"]["content"] or "",
            model_id=self._model_id,
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            finish_reason=choice.get("finish_reason"),
        )

    async def stream(
        self,
        *,
        messages: Sequence[Message],
        max_tokens: int,
        temperature: float,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> AsyncIterator[str]:
        """Yield content deltas; report token usage through `on_usage` when the server
        sends it.

        S20.13: an OpenAI-compatible server reports usage on a stream ONLY if asked, via
        stream_options.include_usage. Nobody asked, so medbot_tokens_total and
        medbot_request_cost_usd recorded NOTHING for streamed requests - and the browser
        streams. Measured: a streamed query moved the counter by 0, the same question
        non-streamed moved it by 1,188. Every "answered" log line read tokens=0, and the
        Grafana cost panels described curl traffic only.

        Guarded with a try/except because not every OpenAI-compatible server implements
        stream_options; a server that ignores it simply never calls on_usage, which
        degrades to the old behaviour rather than failing the stream.
        """
        payload = self._payload(messages, max_tokens, temperature, stream=True)
        payload["stream_options"] = {"include_usage": True}
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    body = line[6:].strip()
                    if body == "[DONE]":
                        return
                    try:
                        chunk = json.loads(body)
                    except json.JSONDecodeError:
                        continue

                    # The usage block arrives in a FINAL chunk that carries no choices.
                    usage = chunk.get("usage")
                    if usage and on_usage is not None:
                        on_usage(
                            Usage(
                                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                                completion_tokens=int(usage.get("completion_tokens") or 0),
                            )
                        )
                    try:
                        delta = chunk["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.venue} stream: {_describe(e)}", cause=e) from e

    async def health(self) -> bool:
        """Cheap liveness probe: /models is free and requires no generation."""
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
