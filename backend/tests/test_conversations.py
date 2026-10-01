from datetime import timedelta

from app.db import utcnow
from app.models import Conversation
from app.services.chat import build_context
from app.models import Message

from .conftest import add_local_provider, stream_events


def new_conv(client, title="New conversation"):
    r = client.post("/conversations", json={"title": title})
    assert r.status_code == 201
    return r.json()["id"]


def test_crud_rename_archive_delete(client):
    cid = new_conv(client, "First")
    assert client.patch(f"/conversations/{cid}", json={"title": "Renamed"}).json()["title"] == "Renamed"
    client.patch(f"/conversations/{cid}", json={"archived": True})
    assert client.get("/conversations").json()["total"] == 0
    assert client.get("/conversations?archived=true").json()["items"][0]["title"] == "Renamed"
    assert client.delete(f"/conversations/{cid}").status_code == 204
    assert client.get(f"/conversations/{cid}").status_code == 404


def test_history_survives_restart(make_client, stub, tmp_path):
    c1 = make_client(tmp_path / "persist")
    add_local_provider(c1, stub)
    cid = new_conv(c1)
    ev = stream_events(c1, cid, content="Remember this sentence about turbines.")
    assert ev[-1]["type"] == "assistant.completed"
    c1.__exit__(None, None, None)
    c2 = make_client(tmp_path / "persist")  # fresh process state, same database file
    conv = c2.get(f"/conversations/{cid}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["messages"][1]["content"] == "Hello from the stub model."
    assert conv["title"].startswith("Remember this sentence")


def test_search_export_and_delete_cleans_index(client, stub):
    add_local_provider(client, stub)
    cid = new_conv(client)
    stream_events(client, cid, content="How do quaternions avoid gimbal lock?")
    hits = client.get("/search", params={"q": "quaternion"}).json()["items"]
    assert any(h["conversation_id"] == cid and h["kind"] == "message" for h in hits)
    j = client.get(f"/conversations/{cid}/export?format=json").json()
    assert j["format"] == "humanoid-companion.conversation" and len(j["messages"]) == 2
    md = client.get(f"/conversations/{cid}/export?format=md").text
    assert "quaternions" in md and "## You" in md
    client.delete(f"/conversations/{cid}")
    assert client.get("/search", params={"q": "quaternion"}).json()["items"] == []


def test_idempotent_client_request_id(client, stub):
    add_local_provider(client, stub)
    cid = new_conv(client)
    stream_events(client, cid, content="hi", client_request_id="req-1")
    r = client.post(f"/conversations/{cid}/messages", json={"content": "hi", "client_request_id": "req-1"})
    assert r.json()["replayed"] is True
    assert len(client.get(f"/conversations/{cid}").json()["messages"]) == 2


def test_regenerate_replaces_last_reply(client, stub):
    add_local_provider(client, stub)
    cid = new_conv(client)
    stream_events(client, cid, content="hi")
    stream_events(client, cid, regenerate=True)
    msgs = client.get(f"/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_retention_purge(make_client, tmp_path):
    c = make_client(tmp_path / "ret")
    cid = new_conv(c)
    c.put("/settings", json={"retention_days": 7})
    state = c.app.state.hc
    with state.session() as db:
        db.get(Conversation, cid).updated_at = utcnow() - timedelta(days=30)
    c.__exit__(None, None, None)
    c2 = make_client(tmp_path / "ret")
    assert c2.get(f"/conversations/{cid}").status_code == 404


def test_context_window_is_bounded(client):
    cid = new_conv(client)
    state = client.app.state.hc
    with state.session() as db:
        for i in range(60):
            db.add(Message(conversation_id=cid, seq=i + 1, role="user" if i % 2 == 0 else "assistant", content=f"msg {i} " + "x" * 400))
    with state.session() as db:
        turns = build_context(db, cid, "sys", max_tokens=1024)
    assert turns[0].role == "system" and turns[1].role == "user"
    assert 2 < len(turns) < 12 and turns[-1].content.startswith("msg 59")
