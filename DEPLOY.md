# Deploying OrderPal (free tier)

Three free services: the app on a **Hugging Face Space** (Gradio SDK as the runtime), Postgres +
pgvector on **Neon**, Redis on **Upstash**. Total cost: ₹0, plus whatever LLM usage the demo generates.

```
browser ──▶ HF Space: python hf_space.py → OrderPal's FastAPI app on port 7860
                 ├──▶ Neon      Postgres 16 + pgvector   (orders, chunks, conversations, usage)
                 ├──▶ Upstash   Redis                    (rate limiting)
                 └──▶ Gemini API                         (LLM)
```

Why the Gradio SDK: Docker Spaces need a paid plan. A Gradio Space runs any Python file that serves
on port 7860, so `hf_space.py` prepares the database and starts our own FastAPI app. There's no
Gradio UI; Gradio is only the free runtime.

## Rules for secrets (read first)
- Connection strings and API keys go **only** into the Space's **Secrets**. Never into `.env`,
  a commit, a chat, or a screenshot. Your local `.env` keeps pointing at the local Docker database.
- If a secret ever appears anywhere else, rotate it: Neon → Roles → reset password; Upstash →
  reset password; Google AI Studio → delete key, create a new one.
- Set a spend limit or budget alert on the Gemini key. A public link means strangers can use it.

## 1. Postgres: Neon
1. Create a project at neon.tech (region: Singapore, closest to India).
2. Copy the **direct** connection string, not the pooled one: in the connect dialog turn **off**
   "Connection pooling", so the host has no `-pooler` in it. It looks like
   `postgresql://user:pass@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
   (Pooled endpoints use PgBouncer transaction mode, which doesn't suit the checkpointer's long-lived
   connections. The app disables prepared statements anyway, but direct is simpler.)
3. Nothing else: the app creates the `vector` extension and all tables on first boot.

## 2. Redis: Upstash
1. Create a Redis database at upstash.com (same region).
2. Copy the **TLS URL**: `rediss://default:<password>@<host>.upstash.io:6379` (`rediss`, two s's = TLS).

## 3. The app: Hugging Face Space
1. huggingface.co → **New Space** → owner + name `orderpal` → SDK **Gradio**, template **Blank**,
   license **apache-2.0**, hardware **CPU basic (free)**, **Public** → Create Space.
2. In the Space: **Settings → Variables and secrets**.
   **Secrets**:
   | name | value |
   |---|---|
   | `DATABASE_URL` | the Neon direct string |
   | `REDIS_URL` | the Upstash `rediss://` URL |
   | `GEMINI_API_KEY` | your key |

   **Variables**: `DEMO_RESEED_ON_START=1`, `RATE_LIMIT_PER_MINUTE=10`
3. Create a Hugging Face **access token** with **write** permission (Settings → Access Tokens).
   Git will ask for it as the password when you push.
4. From the project folder, add the Space as a git remote and publish:
   ```bash
   git remote add space https://huggingface.co/spaces/<your-hf-username>/orderpal
   sh scripts/push_space.sh
   ```
   The script pushes the current commit plus a Space-only commit (Space config at the top of
   README.md, and `requirements-space.txt` as `requirements.txt`). GitHub never sees that commit.
   Commit your work first: the script publishes `HEAD`, not uncommitted changes.
5. Watch **Logs** in the Space. The first build takes ~10 minutes (PyTorch). On boot it runs
   migrations, loads demo data, embeds the policies (downloads two small models the first time),
   then serves the chat page.

## Free-tier behaviour to know
- The Space **sleeps after inactivity**. The first visit afterwards takes about a minute to wake.
  With `DEMO_RESEED_ON_START=1` each wake reloads demo data, so in-progress orders look fresh.
- Neon suspends idle databases; the first query after that is a bit slower.

## Check it works
- `https://<your-hf-username>-orderpal.hf.space/health` → `{"status":"ok","db":"ok","redis":"ok"}`
- Open the Space, pick a customer, click a suggestion.
- `/admin/usage` shows requests, tokens and latency once people use it.

## Troubleshooting
| Log shows | Cause | Fix |
|---|---|---|
| `connection refused` / timeout to Neon | Wrong string, or pooled host | Use the direct string with `?sslmode=require` |
| `prepared statement ... does not exist` | Pooled (`-pooler`) host | Switch to the direct string |
| Redis `Connection reset` | `redis://` instead of `rediss://` | Use the TLS URL |
| `GEMINI_API_KEY is not set` on first chat | Secret missing or misspelled | Add it under Secrets, restart the Space |
| Build fails resolving packages | Gradio version changed | Keep `sdk_version` in `scripts/push_space.sh` at a tested version |

## Running the same app locally in Docker
The `Dockerfile` still works anywhere Docker runs (e.g. Google Cloud Run):
```bash
docker build -t orderpal .
docker run --rm -p 7860:7860 --env-file .env \
  -e DATABASE_URL=postgresql://orderpal:orderpal@host.docker.internal:5433/orderpal \
  -e REDIS_URL=redis://host.docker.internal:6380/0 orderpal
```
