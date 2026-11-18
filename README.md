# OrderPal

**An agentic support-resolution engine for food delivery.** It resolves order, refund, cancellation
and allergen questions end to end. An LLM runs the conversation, while every money decision goes
through deterministic policy code. Retrieval quality, hallucination and attack resistance are
measured with labelled eval sets and gated in CI.

> All data is fictional: a made-up platform "OrderPal" with seeded restaurants, orders and policies.

## Why it's built this way
| Problem in typical LLM support bots | What OrderPal does |
|---|---|
| The model decides refunds and can be talked into anything | Refund, cancellation and late-delivery rules are **plain Python** ([rules.py](app/agent/rules.py)), fully unit-tested. The LLM only explains their result, and there is **no tool that issues refunds** at all. |
| Users can ask about other people's orders | Ownership is checked **in SQL**. `user_id` is injected by the server and hidden from the model's tool schema. |
| "It seems to work" | Labelled eval sets for **retrieval**, **faithfulness** and **red-team attacks**, with results below |
| Vector search misses exact terms | Hybrid Postgres full-text + pgvector search, fused with **RRF**, then a **cross-encoder reranker** |
| Forgets everything, or remembers too much | Conversation memory in Postgres (per-user threads, trimmed context) and long-term preferences restricted to an allow-list **enforced by a DB constraint** |
| Locked into one app | The same tools are exposed as an **MCP server**, with the same ownership rules |

## Results
**Retrieval**: 33 labelled questions, recall@1 = the right policy section ranked first ([evals/run_retrieval.py](evals/run_retrieval.py))

| mode | recall@1 | recall@5 | MRR | median latency |
|---|---|---|---|---|
| vector only (baseline) | 69.7% | 97.0% | 0.808 | 28 ms |
| keyword only | 63.6% | 90.9% | 0.754 | 2 ms |
| hybrid (RRF) | 72.7% | 97.0% | 0.836 | 28 ms |
| **hybrid + cross-encoder rerank** | **81.8%** | **100%** | **0.882** | 283 ms |

**Faithfulness**: an LLM judge checks every claim in every answer against the retrieved passages ([evals/run_faithfulness.py](evals/run_faithfulness.py))

| variant | in-scope + out-of-scope (39) | near-miss traps (10) |
|---|---|---|
| naive prompt + vector search | 0 hallucinated answers, 2 in-scope refusals | **2 hallucinated**, 4 refused |
| grounded prompt + rerank | 0 hallucinated answers, 4 in-scope refusals | **0 hallucinated**, 6 refused |

Near-miss traps are plausible questions the policies only partly answer (e.g. "what's the delivery fee?").
That's where models fill gaps from general knowledge. The honest trade-off: grounding removed those
hallucinations but **refuses more**. The judge is itself an LLM, so its verdicts were spot-checked by hand.

**Red team**: 20 attacks (prompt injection, fake policies, impersonation, data exfiltration, prompt
leaking, memory poisoning, SQL in tool arguments), scored by deterministic checks, not an LLM
([evals/redteam.jsonl](evals/redteam.jsonl)). Result: see `evals/results/redteam.json` after a run.

## Architecture
```
            ┌──────────────────────────── FastAPI ────────────────────────────┐
 chat page ▶│ /chat/stream (SSE) ─▶ LangGraph agent ─┬─▶ tools ─▶ rules.py (refund/cancel)
            │        ▲ rate limit (Redis)             │          └▶ Postgres (orders, menus)
            │        │                                └─▶ search_policies ─▶ hybrid + rerank
            │  memory: checkpoints + preferences (Postgres)        (pgvector + full-text)
            │  usage: tokens, cost, p50/p95 latency ─▶ /admin/usage
            └──────────────────────────────────────────────────────────────────┘
  MCP clients ──▶ app/mcp_server.py (same tools, same rules, one account per server)
  LLM: Gemini, with automatic fallback to a second model on error or timeout
```

## Run it locally
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # then put your GEMINI_API_KEY in .env
docker compose up -d --wait        # Postgres+pgvector on :5433, Redis on :6380
python3 -m scripts.migrate         # schema changes + LangGraph checkpoint tables
python3 -m scripts.seed            # fake restaurants, menus, 120 orders, policy docs
python3 -m scripts.ingest          # chunk + embed the policy docs
uvicorn app.main:app --reload      # chat page: http://localhost:8000  ·  API docs: /docs
```
Other entry points:
```bash
python3 -m scripts.chat --user 4                 # terminal chat, shows every tool call
python3 -m evals.run_retrieval --compare         # retrieval ablation
python3 -m evals.run_faithfulness                # hallucination eval (uses the LLM)
python3 -m evals.run_redteam                     # attack suite (uses the LLM)
ORDERPAL_USER_ID=4 python3 -m app.mcp_server     # MCP server over stdio
pytest -q                                        # 56 offline tests;  pytest -m live  for LLM tests
```

## Endpoints
| | |
|---|---|
| `GET /` | chat page |
| `POST /chat/stream` | agent, streamed as Server-Sent Events (tool calls + tokens) |
| `POST /chat` | agent, single JSON response |
| `POST /ask` | single-shot RAG answer with citations |
| `GET /search?q=&mode=vector\|keyword\|hybrid\|rerank` | retrieval only |
| `GET/DELETE /users/{id}/preferences` | what the assistant remembers, and forgetting it |
| `GET /admin/usage` | requests, tokens, cost, p50/p95 latency |

## Production details
- **Model fallback:** a second Gemini model takes over when the primary errors or times out (hard 30 s timeout).
- **Rate limiting:** a per-user fixed window in Redis, `429` with `Retry-After`.
- **Cost tracking:** every LLM request is logged with tokens and latency. Set prices in `.env` to get ₹ per request.
- **CI** ([.github/workflows/ci.yml](.github/workflows/ci.yml)): fresh Postgres and Redis, tests, and a **retrieval quality gate** (fails if recall@1 < 75%). The LLM evals run on manual trigger.
- **Docker:** a single image with the models baked in. See [DEPLOY.md](DEPLOY.md) for free hosting.

## Known limitations
- The eval sets are small (33 / 49 / 20 items), so the numbers are directional, not precise.
- The embedding model and reranker are English-only. Hinglish works only partly, thanks to the English words inside it.
- `user_id` comes from the request body as a stand-in for authentication. A real deployment needs auth (JWT/OAuth).
- A fixed-window rate limit allows bursts at window boundaries. A token bucket would fix that.

Design decisions and per-phase notes: [ROADMAP.md](ROADMAP.md).
