"""Applies db/migrations/*.sql in name order, then creates LangGraph's checkpoint tables.

    python3 -m scripts.migrate      (idempotent: every migration uses IF NOT EXISTS)

schema.sql only runs when the Postgres volume is first created. Changes after that need
migrations, the same way you'd change a production database without wiping it.
"""
import asyncio
from pathlib import Path

import psycopg

from app.agent.memory import make_checkpointer
from app.config import get_settings


async def main() -> None:
    with psycopg.connect(get_settings().database_url) as conn:
        if conn.execute("SELECT to_regclass('public.users')").fetchone()[0] is None:
            # Fresh database (e.g. a new hosted Postgres): docker-compose never ran schema.sql here.
            conn.execute(Path("db/schema.sql").read_text())
            print("applied schema.sql (fresh database)")
        for f in sorted(Path("db/migrations").glob("*.sql")):
            conn.execute(f.read_text())
            print("applied", f.name)
        conn.commit()
    async with make_checkpointer() as (_, saver):
        await saver.setup()               # LangGraph's own tables: checkpoints, checkpoint_writes, ...
    print("checkpoint tables ready")


if __name__ == "__main__":
    asyncio.run(main())
