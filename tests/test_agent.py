"""Phase 5. The rules are pure functions, so they're tested exhaustively with no DB and no LLM.
That's the payoff of keeping money logic out of the model."""
from datetime import datetime, timedelta, timezone

import pytest

from app.agent import rules
from app.agent.tools import check_cancellation, get_order_details
from app.config import get_settings

NOW = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc)


def order(status="delivered", placed_min_ago=120, eta=30, delivered_min_ago=60, total=500):
    placed = NOW - timedelta(minutes=placed_min_ago)
    delivered = NOW - timedelta(minutes=delivered_min_ago) if status == "delivered" else None
    return {"status": status, "placed_at": placed, "eta_minutes": eta, "delivered_at": delivered,
            "total_inr": total}


# ---------- cancellation ----------
def test_free_within_60_seconds():
    assert rules.cancellation_options(order("preparing", placed_min_ago=0.5), NOW)["fee_inr"] == 0


def test_preparing_costs_full_order_value():
    r = rules.cancellation_options(order("preparing", placed_min_ago=10, eta=30, total=420), NOW)
    assert r["can_cancel"] is True and r["fee_inr"] == 420


def test_late_order_cancels_free():
    r = rules.cancellation_options(order("preparing", placed_min_ago=70, eta=30), NOW)   # 40 min late
    assert r["can_cancel"] is True and r["fee_inr"] == 0


def test_out_for_delivery_needs_support():
    assert rules.cancellation_options(order("out_for_delivery", placed_min_ago=20), NOW)["can_cancel"] is False


def test_policy_gap_is_admitted_not_invented():
    assert rules.cancellation_options(order("placed", placed_min_ago=5), NOW)["can_cancel"] is None


def test_delivered_cannot_be_cancelled():
    assert rules.cancellation_options(order("delivered"), NOW)["can_cancel"] is False


# ---------- refunds ----------
def test_refund_within_48h():
    r = rules.refund_eligibility(order(delivered_min_ago=60 * 47), "missing_items", NOW)
    assert r["eligible"] is True


def test_refund_after_48h_rejected():
    assert rules.refund_eligibility(order(delivered_min_ago=60 * 49), "quality_issue", NOW)["eligible"] is False


def test_not_delivered_has_2h_window_and_full_amount():
    assert rules.refund_eligibility(order(delivered_min_ago=180), "not_delivered", NOW)["eligible"] is False
    r = rules.refund_eligibility(order(delivered_min_ago=60, total=640), "not_delivered", NOW)
    assert r["eligible"] is True and r["max_refund_inr"] == 640


def test_refund_needs_delivered_order():
    assert rules.refund_eligibility(order("preparing"), "missing_items", NOW)["eligible"] is False


# ---------- lateness ----------
@pytest.mark.parametrize("late,comp,amount", [(5, "none (on time)", 0), (15, "OrderPal Wallet credit", 30),
                                              (45, "delivery fee refunded", 40), (75, "full order refund", 500)])
def test_late_compensation_tiers(late, comp, amount):
    o = order(placed_min_ago=200, eta=30, delivered_min_ago=200 - 30 - late)
    r = rules.late_compensation(o, NOW)
    assert (r["minutes_late"], r["compensation"], r["amount_inr"]) == (late, comp, amount)


# ---------- tools: ownership ----------
async def _someone_elses_order(pool, user_id):
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT id FROM orders WHERE user_id <> %s LIMIT 1", (user_id,))).fetchone()
    return row["id"]


async def test_tools_hide_other_users_orders(pool):
    other = await _someone_elses_order(pool, user_id=1)
    cfg = {"configurable": {"pool": pool, "user_id": 1}}
    for t in (get_order_details, check_cancellation):
        assert "No order with that id" in await t.ainvoke({"order_id": other}, config=cfg)


def test_llm_cannot_see_user_id_argument():
    # the model-facing schema must not offer user_id / config, or the LLM could choose them
    assert set(get_order_details.args) == {"order_id"}


# ---------- live: the real agent picks the right tools ----------
needs_key = pytest.mark.skipif(not get_settings().gemini_api_key, reason="GEMINI_API_KEY not set")


@pytest.mark.live
@needs_key
async def test_live_my_last_order_uses_recent_orders(pool, agent):
    from app.agent.graph import run_agent
    r = await run_agent(agent, pool, 1, "what's the status of my most recent order?")
    assert r["tool_calls"][0]["tool"] == "get_my_recent_orders"


@pytest.mark.live
@needs_key
async def test_live_refund_goes_through_rules(pool, agent):
    from app.agent.graph import run_agent
    r = await run_agent(agent, pool, 1, "My last delivered order was missing an item. Can I get a refund?")
    assert "check_refund_eligibility" in [t["tool"] for t in r["tool_calls"]]
