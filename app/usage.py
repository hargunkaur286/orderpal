"""Cost and latency tracking. Every LLM-backed request writes one row to llm_usage, and
GET /admin/usage summarises it: requests, tokens, cost per request, p50/p95 latency.

Why: LLM cost scales with traffic. "What does one resolved query cost?" is the first question
anyone running this at Zomato's volume would ask, and you can't answer it without measuring.
"""
import logging

from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

log = logging.getLogger("orderpal.usage")


def cost_inr(input_tokens: int, output_tokens: int) -> float:
    s = get_settings()
    usd = (float(input_tokens) * s.llm_price_input_usd_per_m + float(output_tokens) * s.llm_price_output_usd_per_m) / 1e6
    return usd * s.usd_to_inr


async def record(pool: AsyncConnectionPool, endpoint: str, user_id: int | None, usage: dict,
                 latency_ms: int, ok: bool = True) -> None:
    """Best effort: a failure to log usage must never fail the user's request."""
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO llm_usage (endpoint, user_id, model, llm_calls, input_tokens, output_tokens,
                                       latency_ms, ok)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (endpoint, user_id, usage.get("model", "?"), usage.get("llm_calls", 0),
                 usage.get("input_tokens", 0), usage.get("output_tokens", 0), latency_ms, ok),
            )
    except Exception:
        log.exception("could not record usage")


async def summary(pool: AsyncConnectionPool, hours: int = 24) -> list[dict]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT endpoint,
                   count(*)                                                    AS requests,
                   round(avg(llm_calls), 2)                                    AS avg_llm_calls,
                   round(avg(input_tokens))                                    AS avg_input_tokens,
                   round(avg(output_tokens))                                   AS avg_output_tokens,
                   sum(input_tokens)                                           AS total_input_tokens,
                   sum(output_tokens)                                          AS total_output_tokens,
                   percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms)    AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)    AS p95_ms,
                   round(100.0 * avg((NOT ok)::int), 1)                        AS error_pct,
                   string_agg(DISTINCT model, ', ')                            AS models
            FROM llm_usage
            WHERE at > now() - make_interval(hours => %s)
            GROUP BY endpoint ORDER BY endpoint
            """,
            (hours,),
        )
        rows = await cur.fetchall()
    for r in rows:
        r["avg_cost_inr"] = round(cost_inr(r["avg_input_tokens"] or 0, r["avg_output_tokens"] or 0), 4)
        r["total_cost_inr"] = round(cost_inr(r["total_input_tokens"] or 0, r["total_output_tokens"] or 0), 2)
    return rows
