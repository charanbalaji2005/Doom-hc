from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Capabilities, ChatTurn, GenParams, LLMProvider, ProviderError, StreamEvent, privacy_of
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

KINDS: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
}
DEFAULT_URLS = {"ollama": "http://127.0.0.1:11434", "openai_compatible": "http://127.0.0.1:8080/v1", "anthropic": "https://api.anthropic.com"}


class PolicyViolation(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def build_provider(kind: str, base_url: str, model: str, api_key: str | None) -> LLMProvider:
    return KINDS[kind](base_url, model, api_key)


def ensure_allowed(kind: str, base_url: str, local_only: bool) -> None:
    if local_only and privacy_of(kind, base_url) == "remote":
        raise PolicyViolation("local_only", "Local-only mode is on, so this remote provider was not contacted.")


__all__ = ["KINDS", "DEFAULT_URLS", "Capabilities", "ChatTurn", "GenParams", "LLMProvider", "ProviderError", "StreamEvent",
           "PolicyViolation", "build_provider", "ensure_allowed", "privacy_of"]
