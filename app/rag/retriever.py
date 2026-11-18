"""Retrieval, in four modes so each improvement can be measured on its own (evals/run_retrieval.py):

    vector   embedding similarity only (the Phase 2 baseline)
    keyword  Postgres full-text search only (exact words, stemmed: "refunds" ~ "refund")
    hybrid   both, merged with Reciprocal Rank Fusion
    rerank   hybrid candidates re-scored by a cross-encoder (the default)

Why combine them: embeddings understand meaning ("money hasn't come back" ~ "refund") but blur
exact terms; keyword search nails exact terms ("scheduled", "UPI", "72 hours") but knows no
synonyms. Each covers the other's blind spot.
"""
import asyncio
from functools import lru_cache
from typing import Literal

from psycopg_pool import AsyncConnectionPool
from sentence_transformers import CrossEncoder

from app.rag.embeddings import embed_query

Mode = Literal["vector", "keyword", "hybrid", "rerank"]
CANDIDATES = 20      # how many each first-stage retriever contributes before fusion / reranking
RRF_K = 60           # standard RRF constant: dampens how much rank 1 beats rank 2
RERANKER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache
def get_reranker() -> CrossEncoder:
    return CrossEncoder(RERANKER)


async def _vector_ids(cur, query: str, n: int) -> list[int]:
    # Encoding is CPU work (~10-50 ms). Run it in a thread so the event loop keeps serving others.
    qvec = await asyncio.to_thread(embed_query, query)
    # `<=>` is pgvector's cosine DISTANCE; ORDER BY the raw expression so the HNSW index is used.
    await cur.execute("SELECT id FROM chunks ORDER BY embedding <=> %s LIMIT %s", (qvec, n))
    return [r["id"] for r in await cur.fetchall()]


async def _keyword_ids(cur, query: str, n: int) -> list[int]:
    # to_tsvector turns the question into stemmed words minus stopwords ("cancelled" -> "cancel");
    # joining them with | means ANY word may match. ts_rank_cd scores how many matched and how
    # close together. (Postgres ranking is BM25-like, not exact BM25.)
    await cur.execute(
        """
        WITH q AS (
            SELECT to_tsquery('english', array_to_string(tsvector_to_array(to_tsvector('english', %s)), ' | ')) AS tsq
        )
        SELECT c.id FROM chunks c, q
        WHERE c.tsv @@ q.tsq
        ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC
        LIMIT %s
        """,
        (query, n),
    )
    return [r["id"] for r in await cur.fetchall()]


def rrf(*rankings: list[int]) -> dict[int, float]:
    """Reciprocal Rank Fusion: score(chunk) = sum over rankings of 1 / (RRF_K + rank).

    Uses only RANKS, never raw scores, because cosine similarity (0..1) and ts_rank (unbounded)
    aren't on comparable scales. A chunk ranked well by both retrievers rises to the top."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + 1 / (RRF_K + rank)
    return scores


async def search(pool: AsyncConnectionPool, query: str, k: int = 5, mode: Mode = "rerank") -> list[dict]:
    """Top-k chunks for the query: dicts with id, source, chunk_index, content, score
    (score's meaning depends on mode, but higher is always better)."""
    async with pool.connection() as conn, conn.cursor() as cur:
        if mode == "vector":
            ids = await _vector_ids(cur, query, CANDIDATES)
            scores = {cid: 1 / (RRF_K + r) for r, cid in enumerate(ids, 1)}
        elif mode == "keyword":
            ids = await _keyword_ids(cur, query, CANDIDATES)
            scores = {cid: 1 / (RRF_K + r) for r, cid in enumerate(ids, 1)}
        else:
            scores = rrf(await _vector_ids(cur, query, CANDIDATES), await _keyword_ids(cur, query, CANDIDATES))

        if not scores:
            return []
        await cur.execute(
            """
            SELECT c.id, d.source, c.chunk_index, c.content
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.id = ANY(%s)
            """,
            (list(scores),),
        )
        rows = {r["id"]: r for r in await cur.fetchall()}

    if mode == "rerank":
        # Cross-encoder: reads query AND chunk together, so it sees how they relate (negation,
        # who-does-what) rather than comparing two independent vectors. Too slow to run on the
        # whole corpus, cheap on ~20 candidates: that's the two-stage "retrieve, then rerank" design.
        candidates = sorted(scores, key=scores.get, reverse=True)[:CANDIDATES]
        logits = await asyncio.to_thread(
            get_reranker().predict, [(query, rows[cid]["content"]) for cid in candidates])
        scores = dict(zip(candidates, map(float, logits)))

    top = sorted(scores, key=scores.get, reverse=True)[:k]
    return [{**rows[cid], "score": scores[cid]} for cid in top]
