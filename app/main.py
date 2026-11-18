import asyncio
import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager

import redis.asyncio as aioredis
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import ratelimit, repo, usage
from app.agent.graph import build_agent, run_agent, stream_agent
from app.agent.memory import make_checkpointer
from app.config import get_settings
from app.db import make_pool
from app.rag import answer as rag_answer
from app.rag import retriever
from app.rag.embeddings import get_model


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after)."""
    app.state.pool = make_pool()
    await app.state.pool.open(wait=True)
    app.state.redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await asyncio.to_thread(get_model)   # load the embedding model now, not on the first request
    await asyncio.to_thread(retriever.get_reranker)   # same for the cross-encoder
    async with AsyncExitStack() as stack:
        _, saver = await stack.enter_async_context(make_checkpointer())
        app.state.agent = build_agent(saver)   # compiled once, shared by every request
        yield
    await app.state.redis.aclose()
    await app.state.pool.close()


app = FastAPI(title="OrderPal", lifespan=lifespan)
log = logging.getLogger("orderpal")


@app.get("/health")
async def health(request: Request):
    """Checks that the dependencies are actually reachable, not just that the process is up."""
    async with request.app.state.pool.connection() as conn:
        await conn.execute("SELECT 1")
    await request.app.state.redis.ping()
    return {"status": "ok", "db": "ok", "redis": "ok"}


@app.get("/orders/{order_id}")
async def get_order(order_id: int, request: Request):
    """FastAPI validates that `order_id` is an int, so a bad id is a 422, not a 500."""
    order = await repo.get_order(request.app.state.pool, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get("/restaurants/{restaurant_id}/menu")
async def get_menu(
    restaurant_id: int,
    request: Request,
    veg_only: bool = False,                 # not in the path, so FastAPI reads it as ?veg_only=
    exclude_allergen: str | None = None,
):
    """Returns 200 with an empty list for an unknown restaurant, matching repo.get_menu.
    (Alternative: 404. Defend your choice in the ROADMAP decisions log.)"""
    items = await repo.get_menu(request.app.state.pool, restaurant_id, veg_only, exclude_allergen)
    return {"restaurant_id": restaurant_id, "items": items}


@app.get("/search")
async def search(request: Request, q: str = Query(min_length=2), k: int = Query(5, ge=1, le=20),
                 mode: retriever.Mode = "rerank"):
    """Search over policy chunks, the retrieval step on its own: see exactly what the LLM will be
    given. ?mode=vector|keyword|hybrid|rerank to compare the strategies side by side."""
    return {"query": q, "mode": mode, "results": await retriever.search(request.app.state.pool, q, k, mode)}


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)   # caps prompt size, so caps cost
    k: int = Field(5, ge=1, le=10)


async def enforce_rate_limit(request: Request, key: str) -> None:
    allowed, retry_after = await ratelimit.allow(request.app.state.redis, key,
                                                 get_settings().rate_limit_per_minute)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests, slow down.",
                            headers={"Retry-After": str(retry_after)})


@app.post("/ask")
async def ask(body: AskRequest, request: Request):
    """Phase 4: retrieve policy chunks, then the LLM answers from them with [n] citations."""
    await enforce_rate_limit(request, f"ip:{request.client.host if request.client else 'unknown'}")
    t0 = time.perf_counter()
    try:
        result = await rag_answer.answer(request.app.state.pool, body.question, body.k)
    except Exception:
        # The LLM is a remote dependency: it can time out, rate-limit or return garbage.
        # Log the details for us; give the client a clean 502 ("upstream failed") instead of a 500.
        log.exception("LLM call failed")
        await usage.record(request.app.state.pool, "ask", None, {}, _ms(t0), ok=False)
        raise HTTPException(status_code=502, detail="The answer service is unavailable, try again.")
    await usage.record(request.app.state.pool, "ask", None, result["usage"], _ms(t0))
    return result


def _ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


class ChatRequest(BaseModel):
    # Stand-in for authentication. In a real app user_id comes from the session/JWT, NEVER from
    # the request body, or anyone could claim to be anyone. See README: Known limitations.
    user_id: int = Field(ge=1)
    message: str = Field(min_length=2, max_length=1000)
    conversation_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    """The agent. Send the returned conversation_id with the next message to continue the chat;
    leave it out to start a new conversation."""
    await enforce_rate_limit(request, f"user:{body.user_id}")
    t0 = time.perf_counter()
    try:
        result = await run_agent(request.app.state.agent, request.app.state.pool,
                                 body.user_id, body.message, body.conversation_id)
    except Exception:
        log.exception("agent failed")
        await usage.record(request.app.state.pool, "chat", body.user_id, {}, _ms(t0), ok=False)
        raise HTTPException(status_code=502, detail="The assistant is unavailable, try again.")
    await usage.record(request.app.state.pool, "chat", body.user_id, result["usage"], _ms(t0))
    return result


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Streaming version of /chat (Server-Sent Events): tool calls and reply tokens as they happen."""
    await enforce_rate_limit(request, f"user:{body.user_id}")
    pool = request.app.state.pool

    async def events():
        t0 = time.perf_counter()
        try:
            async for event in stream_agent(request.app.state.agent, pool, body.user_id,
                                            body.message, body.conversation_id):
                if event["type"] == "done":
                    await usage.record(pool, "chat", body.user_id, event["usage"], _ms(t0))
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception:
            # Headers (200) are already sent once streaming starts, so errors travel as an event.
            log.exception("agent stream failed")
            await usage.record(pool, "chat", body.user_id, {}, _ms(t0), ok=False)
            yield f"data: {json.dumps({'type': 'error', 'detail': 'The assistant is unavailable, try again.'})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/users/{user_id}/orders")
async def recent_orders(user_id: int, request: Request, limit: int = Query(6, ge=1, le=20)):
    """A customer's recent orders (for the chat page's order panel)."""
    return await repo.get_recent_orders(request.app.state.pool, user_id, limit)


@app.get("/users/{user_id}/preferences")
async def get_preferences(user_id: int, request: Request):
    """What the assistant remembers about a user. Users should always be able to see this..."""
    return await repo.get_preferences(request.app.state.pool, user_id)


@app.delete("/users/{user_id}/preferences")
async def forget_preferences(user_id: int, request: Request):
    """...and wipe it (the "right to be forgotten")."""
    return {"deleted": await repo.delete_preference(request.app.state.pool, user_id)}


@app.get("/admin/usage")
async def usage_report(request: Request, hours: int = Query(24, ge=1, le=24 * 30)):
    """Requests, tokens, cost per request and p50/p95 latency per endpoint.
    (A real deployment would protect /admin/* with staff auth.)"""
    return {"hours": hours, "by_endpoint": await usage.summary(request.app.state.pool, hours)}


STATIC = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def chat_page():
    """The demo chat page (single static file, no build step)."""
    return FileResponse(STATIC / "index.html")
