from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request

from app import repo
from app.config import get_settings
from app.db import make_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup (before `yield`) and once at shutdown (after)."""
    app.state.pool = make_pool()
    await app.state.pool.open(wait=True)
    app.state.redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()
    await app.state.pool.close()


app = FastAPI(title="OrderPal", lifespan=lifespan)


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
