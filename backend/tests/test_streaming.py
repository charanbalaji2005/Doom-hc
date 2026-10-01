import time

from .conftest import add_local_provider, stream_events


def conv(client):
    return client.post("/conversations", json={}).json()["id"]


def test_event_sequence_and_real_metrics(client, stub):
    add_local_provider(client, stub)
    ev = stream_events(client, conv(client), content="hello")
    types = [e["type"] for e in ev]
    assert types[0] == "assistant.started" and types[-1] == "assistant.completed"
    assert "".join(e["data"]["text"] for e in ev if e["type"] == "assistant.delta") == "Hello from the stub model."
    m = ev[-1]["data"]["metrics"]
    assert m["ttft_ms"] is not None and m["output_tokens"] == 5 and m["input_tokens"] == 12
    assert all(e["v"] == 1 for e in ev)
    sent = stub.bodies[-1]["messages"]
    assert sent[0]["role"] == "system" and sent[-1] == {"role": "user", "content": "hello"}


def test_ollama_engine_reported_tokens_per_second(client, stub):
    add_local_provider(client, stub, model="stub-model", kind="ollama")
    m = stream_events(client, conv(client), content="hi")[-1]["data"]["metrics"]
    assert m["tokens_per_s"] == 20.0 and m["tokens_per_s_source"] == "engine"


def test_cancel_mid_stream_keeps_partial_text(live_server, stub):
    import json
    http = live_server
    assert http.post("/providers", json={"name": "S", "kind": "openai_compatible", "base_url": stub.url + "/v1", "model": "slow"}).status_code == 201
    cid = http.post("/conversations", json={}).json()["id"]
    events = []
    t0 = time.perf_counter()
    with http.stream("POST", f"/conversations/{cid}/messages", json={"content": "count"}) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            e = json.loads(line[6:])
            events.append(e)
            if e["type"] == "assistant.delta" and sum(x["type"] == "assistant.delta" for x in events) == 3:
                assert http.post(f"/messages/{e['message_id']}/cancel").json()["cancelled"] is True
    elapsed = time.perf_counter() - t0
    assert events[-1]["type"] == "assistant.cancelled"
    assert elapsed < 3.0  # a full reply would take about 6 s
    msg = http.get(f"/conversations/{cid}").json()["messages"][-1]
    assert msg["status"] == "cancelled" and msg["content"].startswith("tick") and msg["content"].count("tick") < 10
    time.sleep(0.4)
    assert stub.hits["client_closed"] >= 1  # the upstream HTTP stream was really closed


def test_streaming_is_incremental_over_real_http(live_server, stub):
    import json
    http = live_server
    http.post("/providers", json={"name": "S", "kind": "openai_compatible", "base_url": stub.url + "/v1", "model": "slow"})
    cid = http.post("/conversations", json={}).json()["id"]
    t0, first = time.perf_counter(), None
    with http.stream("POST", f"/conversations/{cid}/messages", json={"content": "x"}) as r:
        for line in r.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:])["type"] == "assistant.delta":
                first = time.perf_counter() - t0
                break
    assert first is not None and first < 1.5  # first token arrives long before the 6 s reply would finish


def test_provider_error_is_reported_honestly(client, stub):
    add_local_provider(client, stub, model="broken")
    cid = conv(client)
    ev = stream_events(client, cid, content="hi")
    assert ev[-1]["type"] == "assistant.failed" and ev[-1]["data"]["error"]["code"] == "provider_error"
    msg = client.get(f"/conversations/{cid}").json()["messages"][-1]
    assert msg["status"] == "error" and msg["content"] == ""


def test_unreachable_provider(client):
    client.post("/providers", json={"name": "Dead", "kind": "ollama", "base_url": "http://127.0.0.1:9", "model": "x"})
    ev = stream_events(client, conv(client), content="hi")
    assert ev[-1]["type"] == "assistant.failed" and ev[-1]["data"]["error"]["code"] == "unreachable"


def test_no_provider_configured(client):
    r = client.post(f"/conversations/{conv(client)}/messages", json={"content": "hi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_provider"
