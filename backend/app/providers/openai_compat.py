from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Capabilities, ChatTurn, GenParams, LLMProvider, ProviderError, StreamEvent, check_status, translate


class OpenAICompatProvider(LLMProvider):
    """Any server implementing /v1/chat/completions (llama.cpp server, vLLM, LM Studio, hosted APIs)."""
    kind = "openai_compatible"
    capabilities = Capabilities(streaming=True, list_models=True, tool_calling=True, json_mode=True, usage_metrics=True)

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def list_models(self) -> list[str]:
        try:
            async with self.client(15) as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers())
                check_status(r)
                return [m.get("id", "") for m in r.json().get("data", [])]
        except (httpx.HTTPError, ValueError, ProviderError) as e:
            raise translate(e) if not isinstance(e, ValueError) else ProviderError("bad_response", "Model list was not valid JSON.")

    async def stream_chat(self, turns: list[ChatTurn], params: GenParams) -> AsyncIterator[StreamEvent]:
        body: dict = {"model": self.model, "messages": [{"role": t.role, "content": t.content} for t in turns],
                      "stream": True, "max_tokens": params.max_tokens, "stream_options": {"include_usage": True}}
        if params.temperature is not None:
            body["temperature"] = params.temperature
        if params.top_p is not None:
            body["top_p"] = params.top_p
        try:
            async with self.client(params.timeout_s) as c:
                async with c.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=self._headers()) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        check_status(r)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except ValueError:
                            raise ProviderError("bad_response", "Malformed stream chunk from provider.")
                        if obj.get("error"):
                            raise ProviderError("provider_error", str(obj["error"])[:300])
                        for ch in obj.get("choices") or []:
                            txt = (ch.get("delta") or {}).get("content")
                            if txt:
                                yield StreamEvent("delta", txt)
                        if obj.get("usage"):
                            u = obj["usage"]
                            yield StreamEvent("usage", usage={"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")})
        except httpx.HTTPError as e:
            raise translate(e)
