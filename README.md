# OrderPal

An agentic RAG support assistant for a (fictional) food-delivery platform. It answers questions like
*"where's my order?"*, *"can I still cancel?"*, *"I'm allergic to peanuts, what can I eat at Dragon Wok?"*
by choosing between **tools** (live order and menu data in Postgres) and **retrieval** over policy docs.

```
            ┌──────────────────────── FastAPI ────────────────────────┐
 user ────▶ │  /chat ──▶ LangGraph agent ──┬──▶ tools ──▶ Postgres     │  (orders, menus)
            │                │             └──▶ RAG ───▶ pgvector     │  (policy chunks)
            │                └── memory (checkpoints, user prefs)     │
            └──────────────────────────────────────────────────────────┘
                     evals: recall@5 · faithfulness · latency
```

## Run it

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d --wait        # Postgres+pgvector on :5433, Redis on :6380
python -m scripts.seed             # fake restaurants, menus, 120 orders, policy docs
uvicorn app.main:app --reload      # http://localhost:8000/docs
pytest -q
```

Progress, tasks and design decisions: see [ROADMAP.md](ROADMAP.md).
