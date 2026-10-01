import asyncio

import pytest

from app.providers import ChatTurn, GenParams, ProviderError, build_provider, privacy_of

from .stub_llm import StubLLM


async def collect(p):
    text, usage = [], None
    async for ev in p.stream_chat([ChatTurn("system", "s"), ChatTurn("user", "hi")], GenParams(max_tokens=50, timeout_s=10)):
        if ev.type == "delta":
            text.append(ev.text)
        else:
            usage = ev.usage
    return "".join(text), usage


@pytest.mark.parametrize("kind,suffix,key", [("openai_compatible", "/v1", None), ("ollama", "", None), ("anthropic", "", "k-123456")])
def test_adapter_contract(stub, kind, suffix, key):
    p = build_provider(kind, stub.url + suffix, "stub-model", key)
    text, usage = asyncio.run(collect(p))
    assert text == "Hello from the stub model." and usage["output_tokens"] == 5
    h = asyncio.run(p.health())
    assert h["ok"] is True and h["model_listed"] is True


def test_auth_errors_are_mapped():
    s = StubLLM(require_key="right-key-123").start()
    try:
        p = build_provider("openai_compatible", s.url + "/v1", "stub-model", "wrong-key-123")
        with pytest.raises(ProviderError) as e:
            asyncio.run(collect(p))
        assert e.value.code == "auth"
        assert asyncio.run(build_provider("openai_compatible", s.url + "/v1", "stub-model", "right-key-123").health())["ok"]
    finally:
        s.stop()


def test_anthropic_requires_key(stub):
    with pytest.raises(ProviderError) as e:
        asyncio.run(collect(build_provider("anthropic", stub.url, "m", None)))
    assert e.value.code == "auth"


def test_privacy_is_derived_not_declared():
    assert privacy_of("ollama", "http://127.0.0.1:11434") == "local"
    assert privacy_of("openai_compatible", "http://localhost:8080/v1") == "local"
    assert privacy_of("openai_compatible", "https://api.example.com/v1") == "remote"
    assert privacy_of("anthropic", "http://127.0.0.1:1") == "remote"


def test_api_key_is_never_returned(client, stub):
    r = client.post("/providers", json={"name": "K", "kind": "openai_compatible", "base_url": stub.url + "/v1", "model": "stub-model",
                                        "api_key": "sk-supersecretvalue123"})
    body = r.json()
    assert body["has_api_key"] is True and "sk-supersecret" not in r.text
    assert "sk-supersecret" not in client.get("/providers").text
    assert client.app.state.hc.secrets.get(f"provider:{body['id']}") == "sk-supersecretvalue123"


def test_validate_endpoint_reports_real_health(client, stub):
    pid = client.post("/providers", json={"name": "S", "kind": "ollama", "base_url": stub.url, "model": "stub-model"}).json()["id"]
    h = client.post(f"/providers/{pid}/validate").json()
    assert h["ok"] and h["model_listed"] and h["latency_ms"] >= 0
