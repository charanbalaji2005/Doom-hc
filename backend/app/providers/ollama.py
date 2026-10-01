from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .base import Capabilities, ChatTurn, GenParams, LLMProvider, ProviderError, StreamEvent, check_status, translate


class OllamaProvider(LLMProvider):
    kind = "ollama"
    capabilities = Capabilities(streaming=True, list_models=True, tool_calling=True, json_mode=True, usage_metrics=True)

    async def list_models(self) -> list[str]:
        try:
            async with self.client(15) as c:
                r = await c.get(f"{self.base_url}/api/tags")
                check_status(r)
                return [m.get("name", "") for m in r.json().get("models", [])]
        except httpx.HTTPError as e:
            raise translate(e)
        except ValueError:
            raise ProviderError("bad_response", "Model list was not valid JSON.")

    async def stream_chat(self, turns: list[ChatTurn], params: GenParams) -> AsyncIterator[StreamEvent]:
        opts: dict = {"num_predict": params.max_tokens}
        if params.temperature is not None:
            opts["temperature"] = params.temperature
        if params.top_p is not None:
            opts["top_p"] = params.top_p
        body = {"model": self.model, "messages": [{"role": t.role, "content": t.content} for t in turns], "stream": True, "options": opts}
        try:
            async with self.client(params.timeout_s) as c:
                async with c.stream("POST", f"{self.base_url}/api/chat", json=body) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        check_status(r)
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            raise ProviderError("bad_response", "Malformed stream chunk from Ollama.")
                        if obj.get("error"):
                            raise ProviderError("provider_error", str(obj["error"])[:300])
                        txt = (obj.get("message") or {}).get("content")
                        if txt:
                            yield StreamEvent("delta", txt)
                        if obj.get("done"):
                            ed = obj.get("eval_duration")
                            yield StreamEvent("usage", usage={"input_tokens": obj.get("prompt_eval_count"), "output_tokens": obj.get("eval_count"),
                                                               "engine_eval_s": (ed / 1e9) if ed else None})
                            break
        except httpx.HTTPError as e:
            raise translate(e)
