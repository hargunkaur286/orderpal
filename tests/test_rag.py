"""Phase 2. Run `python -m scripts.ingest` first. These hit the real model and DB."""
from app.rag import retriever
from app.rag.chunker import MAX_CHARS, chunk_markdown

DOC = """# Refund Policy

*disclaimer*

## Time limits

Requests within 48 hours.

## How money comes back

Wallet is instant.
"""


def test_chunks_follow_sections_and_carry_title():
    chunks = chunk_markdown(DOC)
    assert [c.content.splitlines()[0] for c in chunks] == [
        "Refund Policy > Time limits", "Refund Policy > How money comes back"]
    assert "disclaimer" not in "".join(c.content for c in chunks)


def test_long_section_is_split_with_overlap():
    paras = [f"Paragraph {i}. " + "x" * 400 for i in range(6)]
    chunks = chunk_markdown("# T\n\n## Big\n\n" + "\n\n".join(paras))
    assert len(chunks) > 1
    assert all(len(c.content) < MAX_CHARS + 500 for c in chunks)
    # the last paragraph of one chunk is repeated at the start of the next
    last_para = chunks[0].content.split("\n\n")[-1]
    assert last_para in chunks[1].content


async def _top_source(pool, q):
    return (await retriever.search(pool, q, k=1))[0]["source"]


async def test_search_finds_right_policy(pool):
    assert await _top_source(pool, "how many days until my card refund shows up") == "policies/refunds.md"
    assert await _top_source(pool, "can I cancel after the restaurant accepted") == "policies/cancellation.md"
    assert await _top_source(pool, "my food came an hour late") == "policies/delivery-delays.md"
    assert await _top_source(pool, "I have a nut allergy") == "policies/allergens-food-safety.md"


async def test_search_scores_are_sorted(pool):
    results = await retriever.search(pool, "refund to wallet", k=5)
    scores = [r["score"] for r in results]
    assert len(results) == 5 and scores == sorted(scores, reverse=True)


def test_search_route(client):
    r = client.get("/search", params={"q": "cancellation fee", "k": 3})
    assert r.status_code == 200 and len(r.json()["results"]) == 3
    assert client.get("/search", params={"q": "x"}).status_code == 422   # too short


# ---------- Phase 7: hybrid search + reranking ----------
from app.rag.retriever import rrf


def test_rrf_rewards_agreement_between_retrievers():
    vector, keyword = [1, 2, 3], [3, 4, 1]
    fused = rrf(vector, keyword)
    order = sorted(fused, key=fused.get, reverse=True)
    assert order[:2] == [1, 3]           # ranked by both beats ranked high by only one
    assert set(fused) == {1, 2, 3, 4}


async def test_keyword_mode_matches_exact_terms(pool):
    top = (await retriever.search(pool, "scheduled", k=1, mode="keyword"))[0]
    assert top["content"].startswith("Cancellation Policy > Scheduled orders")


async def test_every_mode_returns_k_sorted_results(pool):
    for mode in ("vector", "keyword", "hybrid", "rerank"):
        results = await retriever.search(pool, "refund to my card", k=3, mode=mode)
        scores = [r["score"] for r in results]
        assert len(results) == 3 and scores == sorted(scores, reverse=True), mode


async def test_keyword_mode_with_only_stopwords_returns_nothing(pool):
    assert await retriever.search(pool, "the and of", k=3, mode="keyword") == []


def test_search_route_mode_param(client):
    assert client.get("/search", params={"q": "refund", "mode": "keyword"}).json()["mode"] == "keyword"
    assert client.get("/search", params={"q": "refund", "mode": "magic"}).status_code == 422
