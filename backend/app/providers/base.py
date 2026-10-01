"""Vendor-neutral LLM provider interface. The frontend never talks to a vendor directly."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import AsyncIterator, Literal
from urllib.parse import urlparse

import httpx

from ..config import is_loopback_host


@dataclass(frozen=True)
class Capabilities:
    streaming: bool = True
    list_models: bool = True
    tool_calling: bool = False
    json_mode: bool = False
    usage_metrics: bool = False
    requires_api_key: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChatTurn:
    role: str
    content: str


@dataclass
class GenParams:
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int = 1024
    timeout_s: float = 120.0


@dataclass
class StreamEvent:
    type: Literal["delta", "usage"]
    text: str = ""
    usage: dict | None = None


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def translate(exc: Exception) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError("timeout", "The provider did not respond in time.")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return ProviderError("unreachable", "Could not connect to the provider. Is it running and is the URL correct?")
    return ProviderError("bad_response", f"Unexpected provider error: {type(exc).__name__}")


def check_status(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    body = r.text[:300] if r.is_stream_consumed or not r.is_stream_consumed else ""
    if r.status_code in (401, 403):
        raise ProviderError("auth", "The provider rejected the credentials.", r.status_code)
    if r.status_code == 404:
        raise ProviderError("not_found", "Endpoint or model not found on the provider.", r.status_code)
    if r.status_code == 429:
        raise ProviderError("rate_limited", "The provider is rate limiting requests.", r.status_code)
    raise ProviderError("provider_error", f"Provider returned HTTP {r.status_code}: {body}", r.status_code)


def privacy_of(kind: str, base_url: str) -> Literal["local", "remote"]:
    """Derived, never user-declared: a provider is local only if it is reached over loopback."""
    if kind == "anthropic":
        return "remote"
    host = urlparse(base_url).hostname or ""
    return "local" if is_loopback_host(host) else "remote"


class LLMProvider(ABC):
    kind: str = ""
    capabilities = Capabilities()

    def __init__(self, base_url: str, model: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self._local = privacy_of(self.kind, self.base_url) == "local"

    def client(self, timeout: float) -> httpx.AsyncClient:
        # Loopback traffic must never go through a system proxy.
        return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0), trust_env=not self._local)

    @abstractmethod
    def stream_chat(self, turns: list[ChatTurn], params: GenParams) -> AsyncIterator[StreamEvent]: ...

    @abstractmethod
    async def list_models(self) -> list[str]: ...

    async def health(self) -> dict:
        t0 = time.perf_counter()
        try:
            models = await self.list_models()
        except ProviderError as e:
            return {"ok": False, "code": e.code, "detail": e.message, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        listed = self.model in models or any(m.split(":")[0] == self.model for m in models)
        return {"ok": True, "model_listed": listed, "models": models[:50],
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "detail": "Connected; model is available." if listed else f"Connected, but model '{self.model}' was not listed."}
