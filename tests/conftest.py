import pytest
from fastapi.testclient import TestClient

from app.db import make_pool
from app.main import app


@pytest.fixture
async def pool():
    p = make_pool()
    await p.open(wait=True)
    yield p
    await p.close()


@pytest.fixture
def client():
    with TestClient(app) as c:   # `with` runs the lifespan (opens pool + redis)
        yield c


@pytest.fixture
async def agent():
    from app.agent.graph import build_agent
    from app.agent.memory import make_checkpointer
    async with make_checkpointer() as (_, saver):
        yield build_agent(saver)
