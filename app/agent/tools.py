"""The agent's tools. The LLM sees each tool's name, docstring and arguments, and decides when to
call it. Docstrings ARE prompts here: they're how the model knows what a tool is for.

Security model: `user_id` and the DB pool come from `config` (set by OUR code from the logged-in
session), never from the LLM's arguments. LangChain hides `config` from the schema the model sees,
so the model cannot ask about another user's orders even if a user tries to talk it into it.
"""
import json
from datetime import datetime, timezone
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app import repo
from app.agent import rules
from app.rag import retriever


def _ctx(config: RunnableConfig):
    c = config["configurable"]
    return c["pool"], c["user_id"]


def _json(obj) -> str:
    return json.dumps(obj, default=str)   # datetimes -> ISO strings


NOT_FOUND = _json({"error": "No order with that id on your account."})


@tool
async def get_my_recent_orders(
    config: RunnableConfig,
    limit: int = 5,
    status: Literal["placed", "preparing", "out_for_delivery", "delivered", "cancelled"] | None = None,
) -> str:
    """List the logged-in user's most recent orders (newest first) with status and restaurant.
    Use when the user says "my order" / "my last order" without giving an order id.
    Filter by status when the user implies one, e.g. "my last delivered order" -> status="delivered"."""
    pool, user_id = _ctx(config)
    return _json(await repo.get_recent_orders(pool, user_id, min(limit, 10), status))


@tool
async def get_order_details(order_id: int, config: RunnableConfig) -> str:
    """Full details of one of the user's orders: items, status, ETA, and how late it is
    (with the on-time-promise compensation the policy gives)."""
    pool, user_id = _ctx(config)
    order = await repo.get_order_for_user(pool, order_id, user_id)
    if order is None:
        return NOT_FOUND
    order["lateness"] = rules.late_compensation(order, datetime.now(timezone.utc))
    return _json(order)


@tool
async def check_cancellation(order_id: int, config: RunnableConfig) -> str:
    """Decide whether one of the user's orders can be cancelled and what fee applies.
    ALWAYS use this for cancellation questions about a specific order. Never decide yourself."""
    pool, user_id = _ctx(config)
    order = await repo.get_order_for_user(pool, order_id, user_id)
    if order is None:
        return NOT_FOUND
    return _json({"order_id": order_id, "status": order["status"],
                  **rules.cancellation_options(order, datetime.now(timezone.utc))})


@tool
async def check_refund_eligibility(
    order_id: int,
    reason: Literal["missing_items", "wrong_item", "quality_issue", "not_delivered"],
    config: RunnableConfig,
) -> str:
    """Decide whether one of the user's orders is eligible for a refund, for a given reason.
    ALWAYS use this for refund questions about a specific order. Never decide yourself.
    Map the user's complaint to a reason: food spilled/stale/expired/unsafe -> quality_issue."""
    pool, user_id = _ctx(config)
    order = await repo.get_order_for_user(pool, order_id, user_id)
    if order is None:
        return NOT_FOUND
    return _json({"order_id": order_id, "reason": reason,
                  **rules.refund_eligibility(order, reason, datetime.now(timezone.utc))})


@tool
async def find_restaurant_menu(
    restaurant_name: str,
    config: RunnableConfig,
    veg_only: bool = False,
    exclude_allergen: Literal["dairy", "gluten", "peanut", "tree nut", "soy", "egg",
                              "shellfish", "sesame"] | None = None,
) -> str:
    """Find a restaurant by name and return its menu (cheapest first), optionally vegetarian-only
    or without one allergen. Allergen tags come from the restaurant and may be incomplete."""
    pool, _ = _ctx(config)
    matches = await repo.find_restaurants(pool, restaurant_name)
    if not matches:
        return _json({"error": f"No restaurant matching '{restaurant_name}'."})
    r = matches[0]
    menu = await repo.get_menu(pool, r["id"], veg_only, exclude_allergen)
    return _json({"restaurant": r, "items": menu, "other_matches": [m["name"] for m in matches[1:]]})


@tool
async def search_policies(query: str, config: RunnableConfig) -> str:
    """Search OrderPal's policy documents (refunds, cancellation, delivery delays, allergens and
    food safety) for general rules. Use for "what is the policy" questions, not for a specific order."""
    pool, _ = _ctx(config)
    chunks = await retriever.search(pool, query, k=4)
    return _json([{"section": c["content"].splitlines()[0], "text": c["content"]} for c in chunks])


# ---------- Phase 6: long-term memory ----------
PreferenceKey = Literal["diet", "allergies", "spice_level", "language", "favourite_cuisine"]


@tool
async def remember_preference(key: PreferenceKey, value: str, config: RunnableConfig) -> str:
    """Save a lasting fact about the user so future conversations can use it, e.g. diet="vegetarian",
    allergies="peanut, shellfish", language="Hinglish". Only when the user states it as an ongoing
    preference ("I'm vegetarian", "remember I'm allergic to..."), not one-off wishes ("veg today").
    Never store addresses, phone numbers, payment details or anything not in the key list."""
    pool, user_id = _ctx(config)
    await repo.set_preference(pool, user_id, key, value.strip()[:200])
    return _json({"saved": {key: value}})


@tool
async def forget_preference(config: RunnableConfig, key: PreferenceKey | None = None) -> str:
    """Delete one remembered preference, or ALL of them if no key is given. Use when the user asks
    you to forget something or says a preference no longer applies."""
    pool, user_id = _ctx(config)
    return _json({"deleted": await repo.delete_preference(pool, user_id, key)})


TOOLS = [get_my_recent_orders, get_order_details, check_cancellation, check_refund_eligibility,
         find_restaurant_menu, search_policies, remember_preference, forget_preference]
