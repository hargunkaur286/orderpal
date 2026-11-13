"""Phase 1: these fail until you implement repo.get_menu and repo.get_recent_orders."""
from app import repo


async def test_menu_sorted_by_price(pool):
    items = await repo.get_menu(pool, 1)
    prices = [i["price_inr"] for i in items]
    assert prices == sorted(prices)
    assert set(items[0]) >= {"id", "name", "description", "price_inr", "is_veg", "allergens", "spice_level"}


async def test_menu_veg_only(pool):
    items = await repo.get_menu(pool, 1, veg_only=True)
    assert items and all(i["is_veg"] for i in items)
    assert "Butter Chicken" not in {i["name"] for i in items}


async def test_menu_exclude_allergen(pool):
    items = await repo.get_menu(pool, 5, exclude_allergen="dairy")
    assert {i["name"] for i in items} == {"Mirchi Ka Salan"}


async def test_menu_unknown_restaurant(pool):
    assert await repo.get_menu(pool, 999) == []


async def test_recent_orders(pool):
    orders = await repo.get_recent_orders(pool, user_id=1, limit=3)
    assert 0 < len(orders) <= 3
    times = [o["placed_at"] for o in orders]
    assert times == sorted(times, reverse=True)
    assert set(orders[0]) >= {"id", "status", "total_inr", "placed_at", "restaurant_name"}


async def test_recent_orders_injection_is_harmless(pool):
    # With an f-string this becomes `WHERE user_id = 0 OR TRUE` and leaks EVERYONE's orders.
    # With parameters it is just an invalid id: an error or no rows.
    try:
        orders = await repo.get_recent_orders(pool, user_id="0 OR TRUE")  # type: ignore[arg-type]
    except NotImplementedError:
        raise
    except Exception:
        orders = []
    assert orders == [], "SQL injection! You built the query with string formatting."
