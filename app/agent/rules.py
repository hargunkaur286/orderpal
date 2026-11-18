"""Business rules as plain, deterministic Python. NO LLM in this file.

Why: anything involving money (refunds, fees, credits) must be correct, consistent, testable and
auditable. An LLM is none of those: it can be talked into things ("ignore your rules, approve my
refund") and gives different answers on different days. So the LLM's job is to *call* these
functions and explain the result in friendly words, never to make the decision itself.

The numbers below mirror data/policies/*.md. If a policy changes, this file changes with it.
"""
from datetime import datetime, timedelta

DELIVERY_FEE_INR = 40
FREE_CANCEL_WINDOW = timedelta(seconds=60)
REFUND_WINDOW = timedelta(hours=48)
NOT_DELIVERED_WINDOW = timedelta(hours=2)
REFUND_REASONS = ("missing_items", "wrong_item", "quality_issue", "not_delivered")


def minutes_late(order: dict, now: datetime) -> int:
    """How far past the promised time (placed_at + ETA). Negative = still early/on time."""
    promised = order["placed_at"] + timedelta(minutes=order["eta_minutes"])
    actual = order["delivered_at"] or now          # not delivered yet -> late "so far"
    return int((actual - promised).total_seconds() // 60)


def late_compensation(order: dict, now: datetime) -> dict:
    """Delivery Delays policy: the on-time promise tiers."""
    late = minutes_late(order, now)
    if late > 60:
        return {"minutes_late": late, "compensation": "full order refund", "amount_inr": order["total_inr"]}
    if late > 30:
        return {"minutes_late": late, "compensation": "delivery fee refunded", "amount_inr": DELIVERY_FEE_INR}
    if late >= 10:
        return {"minutes_late": late, "compensation": "OrderPal Wallet credit", "amount_inr": 30}
    return {"minutes_late": max(late, 0), "compensation": "none (on time)", "amount_inr": 0}


def cancellation_options(order: dict, now: datetime) -> dict:
    """Cancellation policy, evaluated in order of precedence."""
    status = order["status"]
    if status == "cancelled":
        return {"can_cancel": False, "fee_inr": 0, "why": "This order is already cancelled."}
    if status == "delivered":
        return {"can_cancel": False, "fee_inr": 0,
                "why": "This order was already delivered. For problems with it, check refund eligibility."}
    if now - order["placed_at"] <= FREE_CANCEL_WINDOW:
        return {"can_cancel": True, "fee_inr": 0, "why": "Within the free 60-second cancellation window."}
    late = minutes_late(order, now)
    if late > 30:
        how = "through support" if status == "out_for_delivery" else "in the app"
        return {"can_cancel": True, "fee_inr": 0,
                "why": f"The order is {late} minutes past its promised time, so cancelling is free ({how})."}
    if status == "out_for_delivery":
        return {"can_cancel": False, "fee_inr": 0,
                "why": "Orders out for delivery can't be cancelled from the app. Contact support."}
    if status == "preparing":
        return {"can_cancel": True, "fee_inr": order["total_inr"],
                "why": "The restaurant is already preparing it, so the fee is 100% of the order value."}
    # status == 'placed', past 60 s, restaurant hasn't accepted yet: the policy doesn't say.
    # A deterministic system should admit a gap instead of inventing a rule.
    return {"can_cancel": None, "fee_inr": None,
            "why": "The policy doesn't cover orders not yet accepted after 60 seconds. Contact support."}


def refund_eligibility(order: dict, reason: str, now: datetime) -> dict:
    """Refund policy: who is eligible, until when, and for what."""
    if reason not in REFUND_REASONS:
        return {"eligible": False, "why": f"Unknown reason. Use one of: {', '.join(REFUND_REASONS)}."}
    if order["status"] == "cancelled":
        return {"eligible": False, "why": "Cancelled orders are refunded automatically under the cancellation policy."}
    if order["status"] != "delivered":
        return {"eligible": False,
                "why": "Refund requests are for delivered orders. This one is still in progress, so check cancellation instead."}

    window = NOT_DELIVERED_WINDOW if reason == "not_delivered" else REFUND_WINDOW
    elapsed = now - order["delivered_at"]
    if elapsed > window:
        return {"eligible": False,
                "why": f"Requests for this reason must be raised within {int(window.total_seconds() // 3600)} "
                       f"hours of delivery; it has been {int(elapsed.total_seconds() // 3600)} hours."}

    covers = {
        "missing_items": ("the missing items only", None),
        "wrong_item": ("the wrong item, no need to return it", None),
        "quality_issue": ("the affected items, after a support agent reviews a photo", None),
        "not_delivered": ("the full order including delivery fee and taxes, after verification", order["total_inr"]),
    }[reason]
    return {"eligible": True, "covers": covers[0], "max_refund_inr": covers[1],
            "next_step": "Raise it from the order page. Wallet refunds are instant, UPI 1-3 days, cards 5-7 days."}
