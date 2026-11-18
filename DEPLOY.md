# Deploying OrderPal (free tier)

Three free services: the app on **Hugging Face Spaces** (Docker), Postgres + pgvector on **Neon**,
Redis on **Upstash**. Total cost: ₹0, plus whatever LLM usage the demo generates.

```
browser ──▶ HF Space (this Docker image: FastAPI + chat page + embedder + reranker)
                 ├──▶ Neon      Postgres 16 + pgvector   (orders, chunks, conversations, usage)
                 ├──▶ Upstash   Redis                    (rate limiting)
                 └──▶ Gemini API                         (LLM)
```

## Before you start: protect your API key
A public link means strangers can send messages that cost you quota or money.
1. In Google AI Studio, set a **spend limit / budget alert** on the key, or use a free-tier-only key.
2. Keep `RATE_LIMIT_PER_MINUTE` low (the default is 10 per user per minute).
3. Never commit `.env`. On the host, keys go in **secrets**, not files.

## 1. Postgres: Neon
1. Create a project at neon.tech (region: Singapore or Mumbai if offered, closest to India).
2. Copy the **connection string**. It looks like `postgresql://user:pass@ep-xxx.region.aws.neon.tech/neondb?sslmode=require`
3. Nothing else: pgvector is available on Neon, and the app runs `CREATE EXTENSION vector` itself on first boot.

## 2. Redis: Upstash
1. Create a Redis database at upstash.com (same region as Neon).
2. Copy the **TLS URL**: `rediss://default:<password>@<host>.upstash.io:6379` (note `rediss`, with two s's = TLS).

## 3. The app: Hugging Face Spaces
1. huggingface.co → **New Space** → SDK **Docker** → blank template → public.
2. In the Space's **Settings → Variables and secrets**, add **secrets**:
   | name | value |
   |---|---|
   | `DATABASE_URL` | the Neon string |
   | `REDIS_URL` | the Upstash `rediss://` URL |
   | `GEMINI_API_KEY` | your key |
   and **variables**: `DEMO_RESEED_ON_START=1`, `RATE_LIMIT_PER_MINUTE=10`
3. Spaces read their settings from YAML at the top of the Space's `README.md`. In the Space repo,
   start README.md with:
   ```yaml
   ---
   title: OrderPal
   emoji: 🍱
   colorFrom: red
   colorTo: gray
   sdk: docker
   app_port: 7860
   ---
   ```
4. Push this project to the Space's git remote (it builds the Dockerfile automatically):
   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/orderpal
   git push space main
   ```
5. The first build takes ~10 minutes (PyTorch + models). On boot the container runs migrations,
   loads demo data and the policy embeddings, then serves the chat page at the Space URL.

## Free-tier behaviour to know
- The Space **sleeps after inactivity**. The first visit afterwards takes ~1 minute to wake.
  With `DEMO_RESEED_ON_START=1` every wake reloads demo data, so "in-progress" orders look fresh.
- Neon also suspends idle databases. The first query after that is a bit slower.

## Check it works
- `https://<your-username>-orderpal.hf.space/health` → `{"status":"ok",...}`
- Open the Space URL, pick a customer, click a suggestion.
- `/admin/usage` shows requests, tokens and latency once people use it.

## Running the same image locally
```bash
docker build -t orderpal .
docker run --rm -p 7860:7860 --env-file .env \
  -e DATABASE_URL=postgresql://orderpal:orderpal@host.docker.internal:5433/orderpal \
  -e REDIS_URL=redis://host.docker.internal:6380/0 orderpal
```
Then open http://localhost:7860.
