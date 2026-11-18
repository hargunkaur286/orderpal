#!/bin/sh
# Container start: bring the database schema up to date, load demo data if needed, start the API.
set -e
python -m scripts.migrate
# DEMO_RESEED_ON_START=1 reloads demo data on every boot. On a free host that sleeps when idle, each
# wake-up then gets fresh "in-progress" orders instead of ones that look days late.
if [ "${DEMO_RESEED_ON_START:-0}" = "1" ] || [ "$(python -m scripts.seed --count-orders)" = "0" ]; then
  python -m scripts.seed
  python -m scripts.ingest
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-7860}"
