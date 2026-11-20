# Deploying OrderPal

The app runs on **Google Cloud Run** from this repo's `Dockerfile`, with Postgres + pgvector on
**Neon** and Redis on **Upstash**. Every push to `main` rebuilds and redeploys automatically.

```
GitHub main ──push──▶ Cloud Build (docker build) ──▶ Artifact Registry ──▶ Cloud Run (scales 0..1)
                                                                              ├──▶ Neon     Postgres + pgvector
browser ──HTTPS──▶ Cloud Run service URL ─────────────────────────────────────├──▶ Upstash  Redis (TLS)
                                                                              └──▶ Gemini API
```

Cost: a demo fits Cloud Run's free tier (2M requests and 360,000 GiB-seconds a month). The ~2 GB
image costs a little in Artifact Registry storage, on the order of a few rupees a month. The budget
alert and the max-instances cap below are what keep it there.

## Rules for secrets (read first)
- Connection strings and API keys go **only** into Google **Secret Manager**. Never into `.env`,
  a commit, a chat, or a screenshot. Your local `.env` keeps pointing at the local Docker database.
- If a secret appears anywhere else, rotate it: Neon → Roles → reset password; Upstash → reset
  password; Google AI Studio → delete the key and create a new one.

## 0. Google Cloud project and a budget alert
1. console.cloud.google.com → create a project, e.g. `orderpal`. Add a billing account (card needed).
2. **Billing → Budgets & alerts → Create budget**: scope this project, amount ₹100 (or $1),
   alerts at 50%, 90%, 100%. A budget alerts, it does not stop spending; the instance cap below does.
3. **APIs & Services → Enable**: Cloud Run Admin API, Cloud Build API, Artifact Registry API,
   Secret Manager API. (The console also offers to enable these when you first need them.)

## 1. Postgres: Neon and Redis: Upstash
- Neon (region Singapore): copy the **direct** connection string (pooling off, no `-pooler` in the
  host), ending in `?sslmode=require`. The app creates the `vector` extension and all tables itself.
- Upstash (same region): copy the **TLS URL** from Connect → Redis:
  `rediss://default:<password>@<name>.upstash.io:6379`. It must start with `rediss://`.

## 2. Secrets
**Security → Secret Manager → Create secret**, three times. Paste only the value: no quotes, no
spaces, no "name ->" prefix.
| secret name | value |
|---|---|
| `orderpal-database-url` | the Neon direct string |
| `orderpal-redis-url` | the Upstash `rediss://` URL |
| `orderpal-gemini-key` | your Gemini API key |

## 3. Create the Cloud Run service
**Cloud Run → Deploy container → Service → "Continuously deploy from a repository"**
1. **Set up with Cloud Build** → connect GitHub → repo `hargunkaur286/orderpal`, branch `^main$`,
   build type **Dockerfile**, source location `/Dockerfile` → Save.
2. **Service name** `orderpal`, **region** `asia-southeast1 (Singapore)` (same region as Neon).
3. **Authentication**: Allow public access (it's a public demo; the app rate-limits per user).
4. **Billing**: request-based. **Scaling**: min instances **0**, max instances **1**.
   (Max 1 caps cost, and it also stops two instances reseeding the demo data at the same time.)
5. **Container(s), Volumes... → Settings**:
   - Container port: `8080` (the default; the app listens on whatever `$PORT` Cloud Run sets)
   - Memory **2 GiB**, CPU **1**
   - Request timeout **300** seconds (chat replies stream over one long request)
   - Startup CPU boost: **on** (faster cold starts)
6. **Variables & Secrets**:
   - Environment variables: `DEMO_RESEED_ON_START` = `1`, `RATE_LIMIT_PER_MINUTE` = `10`
   - **Reference a secret** (exposed as environment variable, version `latest`):
     `DATABASE_URL` ← `orderpal-database-url`, `REDIS_URL` ← `orderpal-redis-url`,
     `GEMINI_API_KEY` ← `orderpal-gemini-key`.
     If the console says the service account can't access the secret, click **Grant** (it adds the
     "Secret Manager Secret Accessor" role).
7. **Create**. The first build takes ~10 minutes (PyTorch + models). Watch it under
   **Cloud Build → History**, then the service's **Logs** tab.

On boot the container runs migrations (and `schema.sql` on an empty database), reloads demo data
(because `DEMO_RESEED_ON_START=1`), embeds the policies, then starts serving. A cold start after
scaling to zero takes roughly 30–60 seconds; after that requests are fast.

## Check it works
- `https://<service-url>/health` → `{"status":"ok","db":"ok","redis":"ok"}`
- Open the service URL, pick a customer, click a suggestion.
- `/admin/usage` shows requests, tokens and latency.

## Troubleshooting
| Logs show | Cause | Fix |
|---|---|---|
| `Redis URL must specify one of the following schemes` | Secret isn't a bare `rediss://` URL | Re-create the secret with only the URL |
| `connection refused` / timeout to Neon | Wrong string or pooled host | Direct string, `?sslmode=require` |
| `Permission denied on secret` | Runtime service account lacks access | Grant "Secret Manager Secret Accessor" |
| `Container failed to start and listen on the port` | Boot took too long or crashed | Read the lines above it in Logs; check the three secrets |
| `Memory limit exceeded` | Under 2 GiB | Set memory to 2 GiB |
| Chat says "assistant is unavailable" | Gemini key missing or quota hit | Check the secret; check AI Studio quota |

## Alternative: Hugging Face Space
`hf_space.py` and `scripts/push_space.sh` run the app inside a Gradio Space. Free accounts get
ZeroGPU hardware for Gradio Spaces, which stops apps that don't use the GPU, so this route needs
HF PRO (for CPU basic hardware) to work.

## Running the image locally
```bash
docker build -t orderpal .
docker run --rm -p 8080:8080 -e PORT=8080 \
  -e DATABASE_URL=postgresql://orderpal:orderpal@host.docker.internal:5433/orderpal \
  -e REDIS_URL=redis://host.docker.internal:6380/0 -e GEMINI_API_KEY=... orderpal
```
