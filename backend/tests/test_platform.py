import logging

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.db import alembic_config, run_migrations
from app.security import RedactingJsonFormatter, register_secret


def test_migrations_create_schema_and_match_models(tmp_path):
    url = f"sqlite:///{tmp_path/'m.db'}"
    run_migrations(url)
    names = set(inspect(create_engine(url)).get_table_names())
    assert {"conversations", "messages", "provider_configs", "app_settings", "robot_action_requests", "audit_events", "messages_fts"} <= names
    command.check(alembic_config(url))  # raises if models drifted from migrations
    with create_engine(url).connect() as c:
        assert c.execute(text("PRAGMA integrity_check")).scalar() == "ok"


def test_auth_required(client):
    assert client.get("/health").status_code == 200  # liveness only, no data
    r = client.get("/conversations", headers={"Authorization": "Bearer nope-nope-nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_refuses_non_loopback_bind(tmp_path):
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, api_token="x" * 20, host="0.0.0.0").check()


def test_oversized_request_rejected(client):
    r = client.post("/conversations", content=b"{" + b" " * 2_100_000 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_logs_redact_secrets():
    register_secret("my-registered-secret-42")
    rec = logging.LogRecord("hc", logging.INFO, "", 0, "key sk-abcdefghijklmnop and my-registered-secret-42, Bearer abcdefghijk", None, None)
    out = RedactingJsonFormatter().format(rec)
    assert "abcdefghijklmnop" not in out and "my-registered-secret-42" not in out and "abcdefghijk" not in out


def test_unknown_setting_rejected(client):
    assert client.put("/settings", json={"telemetry": True}).status_code == 422
    assert client.put("/settings", json={"max_context_tokens": 10}).status_code == 422
