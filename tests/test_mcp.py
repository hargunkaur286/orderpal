"""Phase 9: the MCP server, tested the way a real MCP client uses it (subprocess over stdio)."""
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _session_call(user_id: str, tool: str, args: dict):
    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"],   # the interpreter running pytest
                                   cwd=os.getcwd(), env={**os.environ, "ORDERPAL_USER_ID": user_id})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        tools = {t.name: t for t in (await s.list_tools()).tools}
        result = await s.call_tool(tool, args)
        return tools, result.content[0].text


async def test_mcp_lists_tools_and_enforces_ownership(pool):
    async with pool.connection() as conn:
        other = (await (await conn.execute(
            "SELECT id FROM orders WHERE user_id <> 4 ORDER BY id LIMIT 1")).fetchone())["id"]
    tools, text = await _session_call("4", "get_order_details", {"order_id": other})
    assert "No order with that id" in text                       # same rules as the agent
    assert tools["check_refund_eligibility"].annotations.read_only_hint is True
    assert tools["forget_preference"].annotations.destructive_hint is True
    assert not any("refund" in n and "check" not in n for n in tools)   # no tool that ISSUES refunds
