from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

ROOT = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def make_engine(url: str) -> Engine:
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return eng


def alembic_config(url: str):
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def run_migrations(url: str) -> None:
    from alembic import command
    command.upgrade(alembic_config(url), "head")
