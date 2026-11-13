CREATE EXTENSION IF NOT EXISTS vector;

-- ---------- Transactional data (what the agent's TOOLS will query) ----------
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE restaurants (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    cuisine  TEXT NOT NULL,
    area     TEXT NOT NULL,
    rating   NUMERIC(2,1) NOT NULL,
    is_open  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE menu_items (
    id             SERIAL PRIMARY KEY,
    restaurant_id  INT NOT NULL REFERENCES restaurants(id),
    name           TEXT NOT NULL,
    description    TEXT NOT NULL,
    price_inr      INT NOT NULL CHECK (price_inr > 0),
    is_veg         BOOLEAN NOT NULL,
    allergens      TEXT[] NOT NULL DEFAULT '{}',   -- e.g. {'dairy','gluten','peanut'}
    spice_level    SMALLINT NOT NULL DEFAULT 0     -- 0 = none .. 3 = very spicy
);
CREATE INDEX ON menu_items (restaurant_id);

CREATE TABLE orders (
    id             BIGSERIAL PRIMARY KEY,
    user_id        INT NOT NULL REFERENCES users(id),
    restaurant_id  INT NOT NULL REFERENCES restaurants(id),
    status         TEXT NOT NULL CHECK (status IN
                     ('placed','preparing','out_for_delivery','delivered','cancelled')),
    total_inr      INT NOT NULL,
    eta_minutes    INT,                             -- promised at checkout
    placed_at      TIMESTAMPTZ NOT NULL,
    delivered_at   TIMESTAMPTZ                      -- NULL until delivered
);
CREATE INDEX ON orders (user_id, placed_at DESC);

CREATE TABLE order_items (
    order_id      BIGINT NOT NULL REFERENCES orders(id),
    menu_item_id  INT NOT NULL REFERENCES menu_items(id),
    qty           INT NOT NULL CHECK (qty > 0),
    price_inr     INT NOT NULL,                     -- snapshot: menu prices change later
    PRIMARY KEY (order_id, menu_item_id)
);

-- ---------- Knowledge base (what RAG will search) ----------
CREATE TABLE documents (
    id       SERIAL PRIMARY KEY,
    source   TEXT NOT NULL UNIQUE,                  -- e.g. 'policies/refunds.md'
    title    TEXT NOT NULL,
    content  TEXT NOT NULL
);

CREATE TABLE chunks (
    id           SERIAL PRIMARY KEY,
    document_id  INT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INT NOT NULL,
    content      TEXT NOT NULL,
    embedding    VECTOR(384),                       -- bge-small-en-v1.5 outputs 384 dims
    UNIQUE (document_id, chunk_index)
);
-- Phase 2 task: you will add the vector index here yourself (and explain why HNSW).
