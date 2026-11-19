"""Hugging Face Space entry point (Gradio SDK).

The Space runs `python hf_space.py` and expects a web server on port 7860. There's no Gradio UI
here: Gradio is only the free hosting runtime. This prepares the database, then serves OrderPal's
own FastAPI app (chat page, API, streaming) on that port.
"""
import os
import subprocess
import sys

import uvicorn


def prepare_database() -> None:
    def run(module: str) -> None:
        subprocess.run([sys.executable, "-m", module], check=True)

    run("scripts.migrate")                       # schema.sql on a fresh database, then migrations
    from scripts.seed import count_orders
    # DEMO_RESEED_ON_START=1: reload demo data on every boot, so a Space waking from sleep shows
    # fresh "in progress" orders instead of ones that look days late.
    if os.environ.get("DEMO_RESEED_ON_START") == "1" or count_orders() == 0:
        run("scripts.seed")
        run("scripts.ingest")


if __name__ == "__main__":
    prepare_database()
    from app.main import app
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
