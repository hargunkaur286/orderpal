"""Phase 9: production hardening. All offline: the LLM is faked or never reached."""
import uuid

import pytest
import redis.asyncio as aioredis
from pydantic import BaseModel

from app import llm, ratelimit, usage
from app.config import get_settings


class Tiny(BaseModel):
    ok: bool


# ---------- model fallback ----------
async def test_falls_back_to_second_model_when_primary_fails(monkeypatch):
    calls = []

    async def fake_call(model, system, prompt, schema, temperature):
        calls.append(model)
        if model == get_settings().llm_model:
            raise TimeoutError("primary overloaded")
        return Tiny(ok=True), {"model": model, "llm_calls": 1, "input_tokens": 3, "output_tokens": 1}

    monkeypatch.setattr(llm, "_call_model", fake_call)
    parsed, used = await llm.generate_json_with_usage("sys", "hi", Tiny)
    assert parsed.ok and calls == [get_settings().llm_model, get_settings().llm_fallback_model]
    assert used["model"] == get_settings().llm_fallback_model


async def test_both_models_failing_raises(monkeypatch):
    async def always_fail(*a, **kw):
        raise TimeoutError("down")
    monkeypatch.setattr(llm, "_call_model", always_fail)
    with pytest.raises(TimeoutError):
        await llm.generate_json_with_usage("sys", "hi", Tiny)


# ---------- rate limiting ----------
async def test_rate_limit_allows_then_blocks():
    r = aioredis.from_url(get_settings().redis_url)
    key = f"test:{uuid.uuid4().hex}"
    results = [(await ratelimit.allow(r, key, limit=3))[0] for _ in range(5)]
    await r.aclose()
    assert results == [True, True, True, False, False]


def test_ask_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 0)
    resp = client.post("/ask", json={"question": "how long does a refund take"})
    assert resp.status_code == 429 and 0 < int(resp.headers["Retry-After"]) <= 60


def test_chat_rate_limit_is_per_user(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 0)
    assert client.post("/chat", json={"user_id": 3, "message": "hello"}).status_code == 429


# ---------- cost tracking ----------
def test_cost_formula(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_price_input_usd_per_m", 0.10)
    monkeypatch.setattr(s, "llm_price_output_usd_per_m", 0.40)
    monkeypatch.setattr(s, "usd_to_inr", 85.0)
    # 10k in + 1k out = 0.001 + 0.0004 USD = 0.0014 USD = 0.119 INR
    assert usage.cost_inr(10_000, 1_000) == pytest.approx(0.119)


async def test_usage_is_recorded_and_summarised(pool):
    marker = f"test-{uuid.uuid4().hex[:8]}"
    try:
        for ms in (100, 200, 900):
            await usage.record(pool, marker, 1, {"model": "m", "llm_calls": 2, "input_tokens": 500,
                                                 "output_tokens": 50}, ms)
        row = next(r for r in await usage.summary(pool) if r["endpoint"] == marker)
        assert row["requests"] == 3 and row["avg_input_tokens"] == 500 and row["p50_ms"] == 200
    finally:                                   # clean up even if an assertion fails
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM llm_usage WHERE endpoint = %s", (marker,))


def test_usage_endpoint(client):
    assert "by_endpoint" in client.get("/admin/usage").json()


# ---------- live: both models must actually exist (a retired fallback fails silently otherwise) ----------
needs_key = pytest.mark.skipif(not get_settings().gemini_api_key, reason="GEMINI_API_KEY not set")


@pytest.mark.live
@needs_key
@pytest.mark.parametrize("which", ["llm_model", "llm_fallback_model"])
async def test_live_configured_models_respond(which):
    model = getattr(get_settings(), which)
    parsed, used = await llm._call_model(model, "Reply with ok=true.", "go", Tiny, 0.0)
    assert parsed.ok is True and used["model"] == model
