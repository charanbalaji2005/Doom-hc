from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .db import make_engine, run_migrations
from .robot.adapter import SimulatorHub
from .security import SecretStore


class ResponseRegistry:
    """Active streamed responses, keyed by assistant message id, for cancellation."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def register(self, mid: str) -> asyncio.Event:
        ev = asyncio.Event()
        self._events[mid] = ev
        return ev

    def cancel(self, mid: str) -> bool:
        ev = self._events.get(mid)
        if ev:
            ev.set()
            return True
        return False

    def done(self, mid: str) -> None:
        self._events.pop(mid, None)

    def active(self) -> int:
        return len(self._events)


class AppState:
    def __init__(self, settings: Settings, secrets: SecretStore) -> None:
        self.settings = settings
        self.secrets = secrets
        self.responses = ResponseRegistry()
        self.hub = SimulatorHub()
        self.started = time.time()
        self.engine = None
        self.SessionLocal: sessionmaker | None = None

    def start(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        run_migrations(self.settings.db_url)
        self.engine = make_engine(self.settings.db_url)
        self.SessionLocal = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
