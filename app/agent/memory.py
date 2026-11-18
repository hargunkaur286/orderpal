"""Short-term memory plumbing: where conversations are saved and how they're identified.

Short-term = the messages of ONE conversation (a LangGraph "thread"), saved by a checkpointer
after every step, so the next request can continue where the last one stopped.
Long-term = facts about the user across conversations: see user_preferences + the memory tools.
"""
from contextlib import asynccontextmanager

from langchain_core.messages import BaseMessage, trim_messages
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

MAX_HISTORY_MESSAGES = 20


def thread_id(user_id: int, conversation_id: str) -> str:
    """Built on the SERVER from the authenticated user. If the client could send a raw thread id,
    user B could pass user A's id and read A's conversation. Namespacing by user makes the same
    conversation_id from two users two different threads."""
    return f"user:{user_id}:conv:{conversation_id}"


@asynccontextmanager
async def make_checkpointer():
    """A separate small pool, because the checkpointer needs autocommit connections
    (each checkpoint write must be durable immediately, not held in an open transaction)."""
    pool = AsyncConnectionPool(
        get_settings().database_url, min_size=1, max_size=5, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True)
    try:
        yield pool, AsyncPostgresSaver(pool)
    finally:
        await pool.close()


def trim_history(messages: list[BaseMessage]) -> list[BaseMessage]:
    """What we SEND to the model each turn: the last N messages, starting on a user message.

    The full history stays saved in Postgres; we just don't pay to resend all of it every turn.
    start_on="human" matters: cutting in the middle could leave a tool result whose tool call
    was trimmed away, and the model API rejects that as malformed.
    """
    return trim_messages(messages, max_tokens=MAX_HISTORY_MESSAGES, token_counter=len,
                         strategy="last", start_on="human")
