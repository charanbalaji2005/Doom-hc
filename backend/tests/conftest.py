from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security import InMemorySecretStore

from .stub_llm import StubLLM

TOKEN = "test-token-0123456789abcdef"


@pytest.fixture
def stub():
    s = StubLLM().start()
    yield s
    s.stop()


@pytest.fixture
def make_client(tmp_path):
    made = []

    def _make(data_dir=None, secrets=None):
        app = create_app(Settings(data_dir=data_dir or tmp_path / "data", api_token=TOKEN), secret_store=secrets or InMemorySecretStore())
        c = TestClient(app)
        c.__enter__()
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        made.append(c)
        return c

    yield _make
    for c in made:
        try:
            c.__exit__(None, None, None)
        except Exception:
            pass


@pytest.fixture
def client(make_client):
    return make_client()


def add_local_provider(client, stub, model="stub-model", kind="openai_compatible"):
    url = stub.url + ("/v1" if kind == "openai_compatible" else "")
    r = client.post("/providers", json={"name": "Stub", "kind": kind, "base_url": url, "model": model})
    assert r.status_code == 201, r.text
    return r.json()


def stream_events(client, cid, **body):
    events = []
    with client.stream("POST", f"/conversations/{cid}/messages", json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


@pytest.fixture
def live_server(tmp_path):
    """A real uvicorn server on a random loopback port (true streaming, unlike TestClient)."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(Settings(data_dir=tmp_path / "live", api_token=TOKEN, port=port), secret_store=InMemorySecretStore())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    http = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Bearer {TOKEN}"}, trust_env=False, timeout=20)
    yield http
    http.close()
    server.should_exit = True
    t.join(5)
