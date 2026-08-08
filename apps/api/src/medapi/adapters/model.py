"""Groq model adapter (D4). Implements ModelPort.

In the locked D4 v2.1 architecture Groq is the hosted *escalation + outage* leg; the
self-hosted vLLM primary arrives in S13 behind this same port. For the S3 thin slice it
is the only generator. The API key comes from injected Settings (D17), never os.environ.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from medcore.schema import Completion, Message, Usage

_ROLE_TO_LC = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}


def _to_lc(messages: Sequence[Message]) -> list[BaseMessage]:
    return [_ROLE_TO_LC[m.role](content=m.content) for m in messages]


class GroqModel:
    """ModelPort backed by Groq via langchain-groq."""

    def __init__(self, api_key: str, model_id: str, timeout: float) -> None:
        self._model_id = model_id
        self._client = ChatGroq(
            api_key=api_key,  # type: ignore[arg-type]
            model=model_id,
            timeout=timeout,
            max_retries=2,
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    async def complete(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> Completion:
        resp = await self._client.ainvoke(
            _to_lc(messages), max_tokens=max_tokens, temperature=temperature
        )
        meta = resp.response_metadata.get("token_usage", {})
        return Completion(
            text=str(resp.content),
            model_id=self._model_id,
            usage=Usage(
                prompt_tokens=int(meta.get("prompt_tokens", 0)),
                completion_tokens=int(meta.get("completion_tokens", 0)),
            ),
            finish_reason=resp.response_metadata.get("finish_reason"),
        )

    async def stream(
        self, *, messages: Sequence[Message], max_tokens: int, temperature: float
    ) -> AsyncIterator[str]:
        async for chunk in self._client.astream(
            _to_lc(messages), max_tokens=max_tokens, temperature=temperature
        ):
            if chunk.content:
                yield str(chunk.content)

    async def health(self) -> bool:
        try:
            await self._client.ainvoke([HumanMessage(content="ping")], max_tokens=1)
            return True
        except Exception:
            return False
