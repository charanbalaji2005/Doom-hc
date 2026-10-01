from .conftest import add_local_provider, stream_events


def test_local_only_never_contacts_remote_provider(client, stub):
    remote = client.post("/providers", json={"name": "Cloud", "kind": "anthropic", "base_url": stub.url, "model": "stub-model",
                                             "api_key": "k-123456789"}).json()
    assert remote["privacy"] == "remote" and remote["requires_network"] is True
    client.put("/settings", json={"local_only": True})
    cid = client.post("/conversations", json={}).json()["id"]
    r = client.post(f"/conversations/{cid}/messages", json={"content": "hi", "provider_id": remote["id"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "local_only"
    assert client.post(f"/providers/{remote['id']}/validate").status_code == 403
    d = client.get("/diagnostics?check_providers=true").json()
    assert d["providers"][0]["health"]["code"] == "local_only"
    assert sum(stub.hits.values()) == 0  # no request of any kind reached the remote endpoint
    assert client.get(f"/conversations/{cid}").json()["messages"] == []  # nothing half-written


def test_local_provider_still_works_in_local_only(client, stub):
    local = add_local_provider(client, stub)
    client.put("/settings", json={"local_only": True})
    cid = client.post("/conversations", json={}).json()["id"]
    assert stream_events(client, cid, content="hi", provider_id=local["id"])[-1]["type"] == "assistant.completed"
