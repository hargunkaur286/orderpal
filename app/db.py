from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings


def make_pool() -> AsyncConnectionPool:
    """One pool per process. Opening a TCP connection + auth on every request costs a few ms;
    a pool keeps connections warm and caps how many we hold open against Postgres."""
    return AsyncConnectionPool(
        get_settings().database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},   # rows come back as dicts, not tuples
        open=False,                          # opened explicitly in the app lifespan
        configure=register_vector_async,     # each new connection learns the pgvector type
    )
