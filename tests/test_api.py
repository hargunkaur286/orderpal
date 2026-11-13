def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "db": "ok", "redis": "ok"}


def test_get_order(client):
    body = client.get("/orders/1").json()
    assert body["id"] == 1
    assert body["items"], "every seeded order has at least one item"


def test_get_order_404(client):
    assert client.get("/orders/999999").status_code == 404


def test_get_order_bad_id(client):
    assert client.get("/orders/abc").status_code == 422


# ---------- Phase 1: these fail until YOU add the menu route ----------

def test_menu_route(client):
    r = client.get("/restaurants/1/menu")
    assert r.status_code == 200
    body = r.json()
    assert body["restaurant_id"] == 1
    assert len(body["items"]) == 6


def test_menu_route_filters(client):
    items = client.get("/restaurants/2/menu", params={"veg_only": True, "exclude_allergen": "peanut"}).json()["items"]
    assert {i["name"] for i in items} == {"Veg Hakka Noodles", "Veg Manchurian"}
