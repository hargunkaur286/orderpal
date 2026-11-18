# OrderPal Roadmap

Anything marked **YOU** is mine to write or to be able to explain line by line. Every phase ends with
interview questions. If you can't answer them out loud in under
a minute each, the phase isn't done.

Legend: ✅ done · 🔨 in progress · ⬜ not started

---

## ✅ Phase 0: Setup (scaffolded)
Docker (Postgres + pgvector, Redis), FastAPI app with lifespan, connection pool, config, seed data, tests.

**YOU:** read every file in `app/`, `db/schema.sql` and `scripts/seed.py` before writing a line.
- [ ] `git init`, then make your first commit yourself. (The commit history is part of the proof this is your project.)
- [ ] Open http://localhost:8000/docs and call `/health` and `/orders/1`.

**Interview Qs**
1. Why a connection *pool*? What happens with `max_size=10` when request #11 arrives?
2. What does FastAPI's `lifespan` do, and why open the pool there instead of at import time?
3. Why does `order_items.price_inr` exist when `menu_items` already has a price?
4. Why is `/health` checking the DB and Redis rather than just returning `"ok"`?

---

## ✅ Phase 1: Data layer (the agent's future tools)
**YOU:**
- [ ] `repo.get_menu`: filters plus price sort. Try for ONE static SQL string.
- [ ] `repo.get_recent_orders`
- [ ] Route `GET /restaurants/{id}/menu` in `main.py`
- [ ] `pytest -q` → **12 passed**
- [ ] Write your answers in the *Decisions log* below

**Interview Qs**
1. Show me why `f"... WHERE user_id = {user_id}"` is dangerous. (Your test `test_recent_orders_injection_is_harmless` demonstrates it.) Why does this matter *more* when an LLM picks the arguments?
2. Index `(user_id, placed_at DESC)`: why that column order? Would `(placed_at, user_id)` work?
3. `= ANY(array)` vs `@>`: which one can use a GIN index?

---

## ✅ Phase 2: RAG ingestion
**Learn:** chunking (size, overlap, splitting on headings), embeddings, cosine similarity, ANN indexes (HNSW vs IVFFlat).
**YOU:**
- [ ] `app/rag/chunker.py`: split policy docs by `##` section, keeping the doc title in each chunk
- [ ] `scripts/ingest.py`: embed chunks with `sentence-transformers` (bge-small, 384 dims) into `chunks.embedding`
- [ ] Add the HNSW index to `schema.sql` (and work out how to apply it to an existing DB)
- [ ] `app/rag/retriever.py` with `search(query, k=5)`, plus a `GET /search?q=` route

**Interview Qs:** Why chunk at all? What breaks with chunks that are too big, or too small? Why normalise embeddings? What does HNSW trade away?

## ✅ Phase 3: Retrieval eval (your first real resume number)
**YOU:**
- [ ] `evals/retrieval.jsonl`: **30+ questions you write by hand**, each with the chunk(s) that answer it. Include tricky ones ("can I cancel after 45 min if it's late?" needs info from 2 docs).
- [ ] `evals/run_retrieval.py` → **recall@5** and **MRR**. Record the baseline below.

**Interview Qs:** recall@k vs precision@k vs MRR? Why hand-label instead of having an LLM generate the questions?

## ✅ Phase 4: Answering with an LLM
**YOU:** `POST /ask`: retrieve → prompt → answer **with citations**, and "I don't know" when the context doesn't cover it.
**Interview Qs:** What's in your system prompt and why? How do you stop the model answering from its own knowledge? Temperature?

## ✅ Phase 5: The agent (LangGraph)
**YOU:** tools `get_order`, `get_recent_orders`, `get_menu`, `search_policies`, plus **`check_refund_eligibility` as plain Python rules** (the LLM must not decide money questions).
`POST /chat` runs the graph.
**Interview Qs:** Agent vs chain: when *not* to use an agent? Why is refund eligibility deterministic code? How do you stop user A asking about user B's order?

## ✅ Phase 6: Memory
**YOU:** short-term memory via a LangGraph checkpointer keyed by `thread_id`, and long-term per-user preferences (e.g. "I'm vegetarian") stored and recalled across sessions.
**Interview Qs:** Context window limits: when do you summarise old turns? What should never be stored as memory?

## ✅ Phase 7: Better retrieval
**YOU:** hybrid search (Postgres `tsvector` BM25-style + vector, merged with **Reciprocal Rank Fusion**), then a cross-encoder reranker. Re-run Phase 3 → before/after numbers.

## ✅ Phase 8: Faithfulness eval and CI
**YOU:** an LLM-as-judge that checks every claim in an answer is supported by the retrieved context → hallucination rate. Run tests and evals in GitHub Actions.

## ✅ Phase 9: Production polish (+ red-team eval, MCP server, cost tracking)
**YOU:** streaming (SSE), timeouts and retries with a fallback model, Redis rate limiting per user, Dockerfile, a README with real numbers, and a demo GIF.

---

## Decisions log (YOU fill this in: it's your interview cheat sheet)
| Decision | What I chose | Why |
|---|---|---|
| Unknown restaurant on `/menu`: 404 or `[]`? | | |
| Which index makes `get_recent_orders` fast | | |
| Retrieval mode | Hybrid (vector + Postgres full-text, RRF) then cross-encoder rerank of top 20 | +12 pts recall@1 for +255 ms; the LLM call after it takes seconds anyway |
| Chunking strategy | One chunk per `##` section, title-prefixed; long sections split by paragraph with 1-paragraph overlap | Policies are one-topic-per-section; keeps a rule and its exceptions together |

## Numbers (these go straight onto the resume)
| Metric | Baseline | After | Phase |
|---|---|---|---|
| recall@1 (33 questions) | 69.7% (vector) | 81.8% (hybrid + rerank) | 3 → 7 |
| recall@5 | 97.0% | 100% | 3 → 7 |
| MRR | 0.808 | 0.882 | 3 → 7 |
| Search latency (median) | 28 ms | 283 ms (reranker on CPU) | 7 |
| Hallucinated answers on 10 near-miss traps | 2 (naive prompt) | 0 (grounded) | 8 |
| In-scope refusals (33 answerable) | 2 (naive) | 4 (grounded) | 8 |
| p95 latency `/chat` | | | 9 |
