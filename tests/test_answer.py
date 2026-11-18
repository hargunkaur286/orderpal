"""Phase 4. Unit tests fake the LLM (fast, free, deterministic). Live tests call Gemini for real:
    pytest -m live
"""
import pytest

from app.config import get_settings
from app.rag import answer as answer_mod
from app.rag.answer import LLMAnswer, answer, build_prompt


def test_prompt_numbers_passages_and_keeps_sources():
    chunks = [{"source": "policies/a.md", "content": "A > x\n\nfirst"},
              {"source": "policies/b.md", "content": "B > y\n\nsecond"}]
    p = build_prompt("why?", chunks)
    assert "[1] (source: policies/a.md)" in p and "[2] (source: policies/b.md)" in p
    assert p.rstrip().endswith("User question: why?")


async def test_bogus_citations_are_dropped(pool, monkeypatch):
    async def fake_llm(system, prompt, schema, temperature=0.1):
        return (LLMAnswer(answerable=True, answer="Refunds take 5-7 days [1][9].", citations=[1, 9, 1]),
                {"model": "fake", "llm_calls": 1, "input_tokens": 10, "output_tokens": 5})
    monkeypatch.setattr(answer_mod, "generate_json_with_usage", fake_llm)

    r = await answer(pool, "card refund time", k=3)
    assert [c["n"] for c in r["citations"]] == [1]        # 9 doesn't exist, duplicate 1 removed
    assert r["citations"][0]["section"].startswith("Refund Policy")


def test_ask_route_validates_input(client):
    assert client.post("/ask", json={"question": "hi"}).status_code == 422          # too short
    assert client.post("/ask", json={"question": "x" * 600}).status_code == 422      # too long


needs_key = pytest.mark.skipif(not get_settings().gemini_api_key, reason="GEMINI_API_KEY not set")


@pytest.mark.live
@needs_key
async def test_live_answers_with_citation(pool):
    r = await answer(pool, "how many days does a refund to my credit card take?")
    assert r["answerable"] is True
    assert "5" in r["answer"] and "7" in r["answer"]
    assert any(c["source"] == "policies/refunds.md" for c in r["citations"])


@pytest.mark.live
@needs_key
async def test_live_says_i_dont_know(pool):
    r = await answer(pool, "what is the delivery partner's monthly salary?")
    assert r["answerable"] is False
