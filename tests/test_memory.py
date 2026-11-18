"""Phase 6: memory. Offline tests need no LLM; live ones check the agent actually USES memory."""
import json
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app import repo
from app.agent.graph import run_agent
from app.agent.memory import thread_id, trim_history
from app.config import get_settings

USER = 10   # a user the other tests don't touch


# ---------- long-term memory: the preferences table ----------
async def test_preferences_upsert_and_forget(pool):
    await repo.delete_preference(pool, USER)
    await repo.set_preference(pool, USER, "diet", "vegetarian")
    await repo.set_preference(pool, USER, "diet", "vegan")            # same key -> overwritten
    await repo.set_preference(pool, USER, "allergies", "peanut")
    assert await repo.get_preferences(pool, USER) == {"allergies": "peanut", "diet": "vegan"}
    assert await repo.delete_preference(pool, USER, "diet") == 1
    assert await repo.delete_preference(pool, USER) == 1                # forget everything
    assert await repo.get_preferences(pool, USER) == {}


async def test_db_rejects_unknown_preference_keys(pool):
    with pytest.raises(Exception):                                    # CHECK constraint, not trust
        await repo.set_preference(pool, USER, "home_address", "somewhere")


def test_preferences_api(client):
    client.delete(f"/users/{USER}/preferences")
    assert client.get(f"/users/{USER}/preferences").json() == {}


# ---------- short-term memory: threads ----------
def test_same_conversation_id_is_a_different_thread_per_user():
    assert thread_id(1, "abc") != thread_id(2, "abc")


async def test_users_cannot_read_each_others_conversations(agent):
    conv = uuid.uuid4().hex
    mine = {"configurable": {"thread_id": thread_id(1, conv)}}
    theirs = {"configurable": {"thread_id": thread_id(2, conv)}}
    await agent.aupdate_state(mine, {"messages": [HumanMessage("my secret order is 15")]})
    assert len((await agent.aget_state(mine)).values["messages"]) == 1
    assert (await agent.aget_state(theirs)).values == {}               # same conv id, nothing visible


def test_trimming_keeps_recent_and_never_starts_on_a_tool_result():
    history = []
    for i in range(15):                                                # 15 turns x 4 messages = 60
        history += [HumanMessage(f"q{i}"),
                    AIMessage("", tool_calls=[{"name": "t", "args": {}, "id": f"c{i}"}]),
                    ToolMessage("result", tool_call_id=f"c{i}"),
                    AIMessage(f"a{i}")]
    kept = trim_history(history)
    assert len(kept) <= 20 and isinstance(kept[0], HumanMessage)
    assert kept[-1].content == "a14"                                   # newest kept


# ---------- live: does the agent use memory? ----------
needs_key = pytest.mark.skipif(not get_settings().gemini_api_key, reason="GEMINI_API_KEY not set")


@pytest.mark.live
@needs_key
async def test_live_follow_up_uses_earlier_turn(pool, agent):
    r1 = await run_agent(agent, pool, 1, "show me my most recent delivered order")
    first_id = json.loads(r1["tool_results"][0])[0]["id"]
    r2 = await run_agent(agent, pool, 1, "items were missing from it, can I get a refund?",
                         r1["conversation_id"])
    refund_calls = [t for t in r2["tool_calls"] if t["tool"] == "check_refund_eligibility"]
    assert refund_calls and refund_calls[0]["args"]["order_id"] == first_id   # "it" resolved


@pytest.mark.live
@needs_key
async def test_live_preference_carries_across_conversations(pool, agent):
    await repo.delete_preference(pool, USER)
    r1 = await run_agent(agent, pool, USER, "Please remember that I'm vegetarian.")
    assert "remember_preference" in [t["tool"] for t in r1["tool_calls"]]
    r2 = await run_agent(agent, pool, USER, "what can I eat at Pizza Piazza?")   # NEW conversation
    menu_calls = [t for t in r2["tool_calls"] if t["tool"] == "find_restaurant_menu"]
    assert menu_calls and menu_calls[0]["args"].get("veg_only") is True
    await repo.delete_preference(pool, USER)
