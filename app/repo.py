"""Data access. Every function takes the pool and returns plain dicts.

RULE: never build SQL with f-strings. Always pass values as parameters:
    await cur.execute("SELECT ... WHERE id = %s", (order_id,))
(That's what stops SQL injection, and later the LLM will be choosing these values!)
"""
from psycopg_pool import AsyncConnectionPool


async def get_order(pool: AsyncConnectionPool, order_id: int) -> dict | None:
    """Returns the order with restaurant name and its line items, or None if not found."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT o.id, o.status, o.total_inr, o.eta_minutes, o.placed_at, o.delivered_at,
                   r.name AS restaurant_name
            FROM orders o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.id = %s
            """,
            (order_id,),
        )
        order = await cur.fetchone()
        if order is None:
            return None

        await cur.execute(
            """
            SELECT m.name, oi.qty, oi.price_inr
            FROM order_items oi
            JOIN menu_items m ON m.id = oi.menu_item_id
            WHERE oi.order_id = %s
            ORDER BY m.name
            """,
            (order_id,),
        )
        order["items"] = await cur.fetchall()
        return order


# ============================ Menus and order history ============================

async def get_menu(
    pool: AsyncConnectionPool,
    restaurant_id: int,
    veg_only: bool = False,
    exclude_allergen: str | None = None,
) -> list[dict]:
    """Menu items for a restaurant, cheapest first. Unknown restaurant -> [].

    One static SQL string: each optional filter switches itself off when its param is unset.
    - (NOT veg_only OR is_veg): veg_only=False makes the left side TRUE, so every row passes.
    - (allergen IS NULL OR NOT allergen = ANY(allergens)): None makes the left side TRUE.
      The ::text cast is needed because Postgres can't infer the type of a bare NULL parameter.
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, name, description, price_inr, is_veg, allergens, spice_level
            FROM menu_items
            WHERE restaurant_id = %s
              AND (NOT %s OR is_veg)
              AND (%s::text IS NULL OR NOT (%s::text = ANY(allergens)))
            ORDER BY price_inr, id
            """,
            (restaurant_id, veg_only, exclude_allergen, exclude_allergen),
        )
        return await cur.fetchall()


async def get_recent_orders(
    pool: AsyncConnectionPool, user_id: int, limit: int = 5, status: str | None = None
) -> list[dict]:
    """A user's most recent orders, newest first, at most `limit`.

    The agent uses this when a user says "my last order" without giving an id.
    Served by the index on orders (user_id, placed_at DESC): Postgres jumps to this user's
    entries, which are already sorted newest-first, and stops after `limit` rows. No sort step.
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT o.id, o.status, o.total_inr, o.placed_at, r.name AS restaurant_name
            FROM orders o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.user_id = %s
              AND (%s::text IS NULL OR o.status = %s)     -- same self-disabling filter as get_menu
            ORDER BY o.placed_at DESC
            LIMIT %s
            """,
            (user_id, status, status, limit),
        )
        return await cur.fetchall()


# ============================ Phase 5: used by the agent's tools ============================

async def get_order_for_user(pool: AsyncConnectionPool, order_id: int, user_id: int) -> dict | None:
    """Like get_order, but only if the order belongs to this user.

    Returns None both when the order doesn't exist AND when it's someone else's, so a caller can't
    probe which order ids exist. The ownership check lives in SQL, not in the LLM's good behaviour.
    """
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM orders WHERE id = %s AND user_id = %s", (order_id, user_id))
        if await cur.fetchone() is None:
            return None
    return await get_order(pool, order_id)


async def find_restaurants(pool: AsyncConnectionPool, name: str, limit: int = 3) -> list[dict]:
    """Fuzzy-ish name lookup, because users say "dragon wok", not "restaurant 2"."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, name, cuisine, area, rating, is_open
            FROM restaurants
            WHERE name ILIKE %s
            ORDER BY rating DESC
            LIMIT %s
            """,
            (f"%{name.strip()}%", limit),   # the % wildcards are part of the VALUE, still parameterised
        )
        return await cur.fetchall()


# ============================ Phase 6: long-term memory ============================

async def get_preferences(pool: AsyncConnectionPool, user_id: int) -> dict[str, str]:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("SELECT key, value FROM user_preferences WHERE user_id = %s ORDER BY key", (user_id,))
        return {r["key"]: r["value"] for r in await cur.fetchall()}


async def set_preference(pool: AsyncConnectionPool, user_id: int, key: str, value: str) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_preferences (user_id, key, value) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            (user_id, key, value),
        )


async def delete_preference(pool: AsyncConnectionPool, user_id: int, key: str | None = None) -> int:
    """Deletes one key, or every preference when key is None. Returns rows deleted."""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM user_preferences WHERE user_id = %s AND (%s::text IS NULL OR key = %s)",
            (user_id, key, key),
        )
        return cur.rowcount
