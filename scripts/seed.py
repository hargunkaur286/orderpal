"""Loads fake restaurants, menus, users and orders, plus the policy docs (without embeddings yet).

Run:  python -m scripts.seed      (safe to re-run: wipes and reloads everything)
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

from app.config import get_settings

random.seed(42)  # deterministic: everyone gets the same orders, so tests/evals are reproducible

# (name, cuisine, area, rating, [ (item, description, price, is_veg, allergens, spice) ])
RESTAURANTS = [
    ("Punjab Da Dhaba", "North Indian", "Rajouri Garden", 4.3, [
        ("Butter Chicken", "Tandoori chicken in a creamy tomato and butter gravy", 380, False, ["dairy"], 1),
        ("Dal Makhani", "Black lentils slow-cooked overnight with butter and cream", 260, True, ["dairy"], 1),
        ("Paneer Tikka", "Chargrilled cottage cheese marinated in yoghurt and spices", 320, True, ["dairy"], 2),
        ("Butter Naan", "Tandoor-baked flatbread brushed with butter", 60, True, ["dairy", "gluten"], 0),
        ("Jeera Rice", "Basmati rice tempered with cumin", 180, True, [], 0),
        ("Chole Bhature", "Spiced chickpeas with two fried breads", 220, True, ["gluten"], 2),
    ]),
    ("Dragon Wok", "Chinese", "Hauz Khas", 4.1, [
        ("Veg Hakka Noodles", "Wok-tossed noodles with vegetables and soy", 210, True, ["gluten", "soy"], 1),
        ("Chilli Chicken", "Crispy chicken tossed with peppers and green chillies", 290, False, ["soy", "gluten", "egg"], 3),
        ("Kung Pao Paneer", "Paneer with peanuts, dried chillies and spring onion", 300, True, ["peanut", "dairy", "soy"], 2),
        ("Veg Manchurian", "Vegetable dumplings in a tangy soy-garlic sauce", 240, True, ["soy", "gluten"], 2),
        ("Prawn Fried Rice", "Fried rice with prawns, egg and scallions", 340, False, ["shellfish", "egg", "soy"], 1),
    ]),
    ("Pizza Piazza", "Italian", "Connaught Place", 4.4, [
        ("Margherita", "Tomato, mozzarella and basil on a thin crust", 299, True, ["gluten", "dairy"], 0),
        ("Pepperoni Feast", "Double pepperoni with mozzarella", 449, False, ["gluten", "dairy"], 1),
        ("Pesto Veggie", "Basil pesto, olives, peppers and pine nuts", 399, True, ["gluten", "dairy", "tree nut"], 0),
        ("Garlic Bread", "Toasted bread with garlic butter", 149, True, ["gluten", "dairy"], 0),
        ("Tiramisu", "Coffee-soaked sponge with mascarpone", 229, True, ["dairy", "egg", "gluten"], 0),
    ]),
    ("Southern Spice", "South Indian", "Lajpat Nagar", 4.5, [
        ("Masala Dosa", "Rice crepe filled with spiced potato", 160, True, [], 1),
        ("Idli Sambar", "Steamed rice cakes with lentil stew", 120, True, [], 1),
        ("Medu Vada", "Crispy lentil doughnuts with coconut chutney", 130, True, [], 1),
        ("Chicken Chettinad", "Fiery Chettinad-style chicken curry", 340, False, [], 3),
        ("Filter Coffee", "South Indian coffee with milk", 70, True, ["dairy"], 0),
    ]),
    ("Biryani Blues", "Mughlai", "Saket", 4.2, [
        ("Hyderabadi Chicken Biryani", "Dum-cooked basmati with chicken and saffron", 360, False, ["dairy"], 2),
        ("Veg Biryani", "Basmati with vegetables, mint and fried onions", 280, True, ["dairy"], 2),
        ("Mutton Korma", "Slow-cooked mutton in a cashew and yoghurt gravy", 450, False, ["tree nut", "dairy"], 2),
        ("Mirchi Ka Salan", "Green chillies in a peanut and sesame gravy", 180, True, ["peanut", "sesame"], 3),
        ("Phirni", "Chilled ground-rice pudding with cardamom", 120, True, ["dairy", "tree nut"], 0),
    ]),
    ("Green Bowl", "Healthy", "Vasant Kunj", 4.6, [
        ("Quinoa Salad", "Quinoa, chickpeas, cucumber and lemon dressing", 290, True, [], 0),
        ("Tofu Buddha Bowl", "Brown rice, tofu, greens and sesame dressing", 340, True, ["soy", "sesame"], 1),
        ("Grilled Chicken Bowl", "Grilled chicken, brown rice and roasted vegetables", 380, False, [], 1),
        ("Peanut Satay Wrap", "Whole-wheat wrap with veggies and peanut sauce", 260, True, ["peanut", "gluten"], 1),
        ("Cold-Pressed Juice", "Orange, carrot and ginger", 160, True, [], 0),
    ]),
    ("Momo Station", "Tibetan", "Malviya Nagar", 4.0, [
        ("Veg Steamed Momos", "Dumplings filled with cabbage and carrot", 140, True, ["gluten"], 1),
        ("Chicken Steamed Momos", "Dumplings filled with minced chicken", 170, False, ["gluten"], 1),
        ("Tandoori Momos", "Chargrilled momos in a spicy marinade", 210, False, ["gluten", "dairy"], 2),
        ("Thukpa", "Tibetan noodle soup with vegetables", 190, True, ["gluten", "soy"], 1),
    ]),
    ("Sweet Truth", "Desserts", "Greater Kailash", 4.3, [
        ("Chocolate Brownie", "Fudgy brownie with walnuts", 150, True, ["gluten", "dairy", "egg", "tree nut"], 0),
        ("Gulab Jamun", "Two warm milk-solid dumplings in syrup", 99, True, ["dairy", "gluten"], 0),
        ("Mango Kulfi", "Traditional Indian ice cream with mango", 120, True, ["dairy", "tree nut"], 0),
        ("Vegan Dark Chocolate Mousse", "Coconut-cream chocolate mousse", 180, True, [], 0),
    ]),
]

USERS = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Saanvi", "Vihaan", "Ananya", "Arjun", "Isha"]
STATUSES = ["delivered"] * 6 + ["cancelled", "placed", "preparing", "out_for_delivery"]


def main() -> None:
    now = datetime.now(timezone.utc)
    with psycopg.connect(get_settings().database_url) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE chunks, documents, order_items, orders, menu_items, restaurants, users "
                    "RESTART IDENTITY CASCADE")

        for name in USERS:
            cur.execute("INSERT INTO users (name) VALUES (%s)", (name,))

        menu: dict[int, list[tuple[int, int]]] = {}   # restaurant_id -> [(item_id, price)]
        for r_name, cuisine, area, rating, items in RESTAURANTS:
            cur.execute("INSERT INTO restaurants (name, cuisine, area, rating) VALUES (%s,%s,%s,%s) "
                        "RETURNING id", (r_name, cuisine, area, rating))
            rid = cur.fetchone()[0]
            menu[rid] = []
            for item, desc, price, veg, allergens, spice in items:
                cur.execute("INSERT INTO menu_items (restaurant_id, name, description, price_inr, is_veg, "
                            "allergens, spice_level) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                            (rid, item, desc, price, veg, allergens, spice))
                menu[rid].append((cur.fetchone()[0], price))

        for _ in range(120):
            user_id = random.randint(1, len(USERS))
            rid = random.choice(list(menu))
            picks = random.sample(menu[rid], k=random.randint(1, min(3, len(menu[rid]))))
            lines = [(item_id, random.randint(1, 2), price) for item_id, price in picks]
            status = random.choice(STATUSES)
            eta = random.choice([25, 30, 35, 40, 45])
            if status in ("placed", "preparing", "out_for_delivery"):
                placed = now - timedelta(minutes=random.randint(2, 50))       # in flight right now
            else:
                placed = now - timedelta(days=random.randint(0, 30), minutes=random.randint(60, 900))
            # Some delivered orders are deliberately late, so the delay policy has something to apply to.
            delivered = placed + timedelta(minutes=eta + random.choice([-5, 0, 5, 15, 35, 70])) \
                if status == "delivered" else None
            total = sum(q * p for _, q, p in lines) + 40   # + flat delivery fee
            cur.execute("INSERT INTO orders (user_id, restaurant_id, status, total_inr, eta_minutes, "
                        "placed_at, delivered_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (user_id, rid, status, total, eta, placed, delivered))
            oid = cur.fetchone()[0]
            for item_id, qty, price in lines:
                cur.execute("INSERT INTO order_items VALUES (%s,%s,%s,%s)", (oid, item_id, qty, price))

        for path in sorted(Path("data/policies").glob("*.md")):
            text = path.read_text()
            title = text.splitlines()[0].lstrip("# ").strip()
            cur.execute("INSERT INTO documents (source, title, content) VALUES (%s,%s,%s)",
                        (f"policies/{path.name}", title, text))

        conn.commit()
    print(f"Seeded {len(USERS)} users, {len(RESTAURANTS)} restaurants, 120 orders, policy docs.")


if __name__ == "__main__":
    main()
