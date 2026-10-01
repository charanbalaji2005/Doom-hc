"""Runtime configuration. Binds to loopback only unless explicitly overridden."""
from __future__ import annotations

import ipaddress
import os
import secrets
import sys
from pathlib import Path

from pydantic import BaseModel, Field


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "humanoid-companion"


def is_loopback_host(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class Settings(BaseModel):
    data_dir: Path
    api_token: str = Field(min_length=16)
    host: str = "127.0.0.1"
    port: int = 8765
    cors_origins: list[str] = [
        "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
        "http://localhost:5173", "http://127.0.0.1:5173",
    ]
    max_request_bytes: int = 2_000_000
    log_level: str = "INFO"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'companion.db').as_posix()}"

    def check(self) -> None:
        if not is_loopback_host(self.host) and os.environ.get("HC_ALLOW_REMOTE_BIND") != "1":
            raise ValueError(f"Refusing to bind to non-loopback host {self.host!r}. Set HC_ALLOW_REMOTE_BIND=1 to override.")


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("HC_DATA_DIR") or default_data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("HC_API_TOKEN")
    if not token:
        tf = data_dir / "api_token"
        if tf.exists():
            token = tf.read_text().strip()
        else:
            token = secrets.token_urlsafe(32)
            tf.write_text(token)
            try:
                tf.chmod(0o600)
            except OSError:
                pass
    s = Settings(data_dir=data_dir, api_token=token, host=os.environ.get("HC_HOST", "127.0.0.1"),
                 port=int(os.environ.get("HC_PORT", "8765")), log_level=os.environ.get("HC_LOG_LEVEL", "INFO"))
    s.check()
    return s
