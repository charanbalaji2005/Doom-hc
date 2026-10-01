from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Capabilities, ChatTurn, GenParams, LLMProvider, ProviderError, StreamEvent, check_status, translate


class AnthropicProvider(LLMProvider):
    kind = "anthropic"
    capabilities = Capabilities(streaming=True, list_models=True, tool_calling=True, json_mode=False, usage_metrics=True, requires_api_key=True)

    def _headers(self) -> dict:
        if not self.api_key:
            raise ProviderError("auth", "This provider needs an API key. Add one in Models.")
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    async def list_models(self) -> list[str]:
        try:
            async with self.client(15) as c:
                r = await c.get(f"{self.base_url}/v1/models", headers=self._headers())
                check_status(r)
                return [m.get("id", "") for m in r.json().get("data", [])]
        except httpx.HTTPError as e:
            raise translate(e)

    async def stream_chat(self, turns: list[ChatTurn], params: GenParams) -> AsyncIterator[StreamEvent]:
        system = "\n\n".join(t.content for t in turns if t.role == "system")
        msgs = [{"role": t.role, "content": t.content} for t in turns if t.role in ("user", "assistant")]
        body: dict = {"model": self.model, "max_tokens": params.max_tokens, "messages": msgs, "stream": True}
        if system:
            body["system"] = system
        if params.temperature is not None:
            body["temperature"] = params.temperature
        headers = self._headers()
        usage: dict = {}
        try:
            async with self.client(params.timeout_s) as c:
                async with c.stream("POST", f"{self.base_url}/v1/messages", json=body, headers=headers) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        check_status(r)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            obj = json.loads(line[5:].strip())
                        except ValueError:
                            raise ProviderError("bad_response", "Malformed stream chunk from provider.")
                        t = obj.get("type")
                        if t == "content_block_delta" and (obj.get("delta") or {}).get("type") == "text_delta":
                            yield StreamEvent("delta", obj["delta"].get("text", ""))
                        elif t == "message_start":
                            usage["input_tokens"] = ((obj.get("message") or {}).get("usage") or {}).get("input_tokens")
                        elif t == "message_delta":
                            usage["output_tokens"] = (obj.get("usage") or {}).get("output_tokens")
                        elif t == "error":
                            raise ProviderError("provider_error", str(obj.get("error"))[:300])
                        elif t == "message_stop":
                            break
            if usage:
                yield StreamEvent("usage", usage=usage)
        except httpx.HTTPError as e:
            raise translate(e)
