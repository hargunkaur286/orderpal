"""OrderPal's tools as an MCP (Model Context Protocol) server.

MCP is a standard way to expose tools to ANY AI client (desktop assistants, IDE agents, other
agent frameworks), instead of wiring them into one app. This server publishes the SAME tool
functions the LangGraph agent uses, so the same rules apply everywhere:
  - ownership is checked in SQL inside the tools, not by whichever client is calling
  - refund/cancellation decisions still come from app/agent/rules.py, never from the client's model
  - there is still no tool that issues refunds or changes orders

Scoping: one server process = one customer account, set by ORDERPAL_USER_ID (in production this
would come from an OAuth token the MCP client presents, which the SDK supports via `auth=`).

Run it (stdio transport, which desktop MCP clients launch as a subprocess):
    ORDERPAL_USER_ID=4 python3 -m app.mcp_server
Example client config (JSON, in the client's MCP settings):
    {"mcpServers": {"orderpal": {"command": "<repo>/.venv/bin/python",
                                 "args": ["-m", "app.mcp_server"], "cwd": "<repo>",
                                 "env": {"ORDERPAL_USER_ID": "4"}}}}
"""
import asyncio
import os
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from app.agent import tools as t
from app.db import make_pool

mcp = MCPServer(
    name="orderpal",
    instructions="Food-delivery support tools for ONE OrderPal customer account: their orders, "
                 "cancellation and refund eligibility (decided by policy rules), restaurant menus "
                 "with allergen filters, policy search, and remembered preferences. Tools cannot "
                 "issue refunds or modify orders.",
)

_pool = None
_lock = asyncio.Lock()
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def _user_id() -> int:
    raw = os.environ.get("ORDERPAL_USER_ID", "")
    if not raw.isdigit():
        raise RuntimeError("Set ORDERPAL_USER_ID to the customer account this server acts for.")
    return int(raw)


async def _call(lc_tool, **args) -> str:
    """Runs one of the agent's LangChain tools with the same injected context the agent uses."""
    global _pool
    async with _lock:
        if _pool is None:
            _pool = make_pool()
            await _pool.open(wait=True)
    config = {"configurable": {"pool": _pool, "user_id": _user_id()}}
    return await lc_tool.ainvoke({k: v for k, v in args.items() if v is not None}, config=config)


Status = Literal["placed", "preparing", "out_for_delivery", "delivered", "cancelled"]
Reason = Literal["missing_items", "wrong_item", "quality_issue", "not_delivered"]
Allergen = Literal["dairy", "gluten", "peanut", "tree nut", "soy", "egg", "shellfish", "sesame"]
PrefKey = Literal["diet", "allergies", "spice_level", "language", "favourite_cuisine"]


@mcp.tool(annotations=READ_ONLY, description=t.get_my_recent_orders.description)
async def get_my_recent_orders(limit: int = 5, status: Status | None = None) -> str:
    return await _call(t.get_my_recent_orders, limit=limit, status=status)


@mcp.tool(annotations=READ_ONLY, description=t.get_order_details.description)
async def get_order_details(order_id: int) -> str:
    return await _call(t.get_order_details, order_id=order_id)


@mcp.tool(annotations=READ_ONLY, description=t.check_cancellation.description)
async def check_cancellation(order_id: int) -> str:
    return await _call(t.check_cancellation, order_id=order_id)


@mcp.tool(annotations=READ_ONLY, description=t.check_refund_eligibility.description)
async def check_refund_eligibility(order_id: int, reason: Reason) -> str:
    return await _call(t.check_refund_eligibility, order_id=order_id, reason=reason)


@mcp.tool(annotations=READ_ONLY, description=t.find_restaurant_menu.description)
async def find_restaurant_menu(restaurant_name: str, veg_only: bool = False,
                               exclude_allergen: Allergen | None = None) -> str:
    return await _call(t.find_restaurant_menu, restaurant_name=restaurant_name, veg_only=veg_only,
                       exclude_allergen=exclude_allergen)


@mcp.tool(annotations=READ_ONLY, description=t.search_policies.description)
async def search_policies(query: str) -> str:
    return await _call(t.search_policies, query=query)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True),
          description=t.remember_preference.description)
async def remember_preference(key: PrefKey, value: str) -> str:
    return await _call(t.remember_preference, key=key, value=value)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True),
          description=t.forget_preference.description)
async def forget_preference(key: PrefKey | None = None) -> str:
    return await _call(t.forget_preference, key=key)


if __name__ == "__main__":
    _user_id()          # fail fast at startup if the account isn't configured
    mcp.run("stdio")
