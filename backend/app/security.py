"""Auth token check, secret storage (OS keyring) and log redaction."""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
import time

_KNOWN_SECRETS: set[str] = set()
_PATTERNS = [re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")]


def register_secret(value: str | None) -> None:
    if value and len(value) >= 6:
        _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    for s in _KNOWN_SECRETS:
        text = text.replace(s, "[redacted]")
    text = _PATTERNS[0].sub("[redacted]", text)
    return _PATTERNS[1].sub(r"\1[redacted]", text)


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
               "level": record.levelname, "logger": record.name, "msg": redact(record.getMessage())}
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    h = logging.StreamHandler()
    h.setFormatter(RedactingJsonFormatter())
    root = logging.getLogger("hc")
    root.handlers[:] = [h]
    root.setLevel(level)
    root.propagate = False


def token_ok(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())


class SecretStoreUnavailable(Exception):
    pass


class SecretStore:
    """API keys live in the OS credential store (Keychain, Credential Manager, Secret Service).
    Fallback for headless setups: environment variable HC_SECRET_<NAME>. Secrets never reach the frontend."""
    SERVICE = "humanoid-companion"

    def __init__(self) -> None:
        try:
            import keyring
            from keyring.backends import fail
            kr = keyring.get_keyring()
            self._kr = keyring
            self.available = not isinstance(kr, fail.Keyring) and getattr(kr, "priority", 1) > 0
            self.backend_name = type(kr).__name__
        except Exception:  # pragma: no cover - depends on platform
            self._kr, self.available, self.backend_name = None, False, "none"

    @staticmethod
    def env_name(name: str) -> str:
        return "HC_SECRET_" + re.sub(r"[^A-Z0-9]", "_", name.upper())

    def set(self, name: str, value: str) -> None:
        if not self.available:
            raise SecretStoreUnavailable(
                f"No OS credential store is available. Set the environment variable {self.env_name(name)} instead.")
        self._kr.set_password(self.SERVICE, name, value)
        register_secret(value)

    def get(self, name: str) -> str | None:
        v = None
        if self.available:
            try:
                v = self._kr.get_password(self.SERVICE, name)
            except Exception:
                v = None
        v = v or os.environ.get(self.env_name(name))
        register_secret(v)
        return v

    def delete(self, name: str) -> None:
        if self.available:
            try:
                self._kr.delete_password(self.SERVICE, name)
            except Exception:
                pass


class InMemorySecretStore(SecretStore):
    """Test double. Never used by the real application entry point."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}
        self.available, self.backend_name = True, "memory (tests only)"

    def set(self, name: str, value: str) -> None:
        self._d[name] = value
        register_secret(value)

    def get(self, name: str) -> str | None:
        return self._d.get(name)

    def delete(self, name: str) -> None:
        self._d.pop(name, None)
