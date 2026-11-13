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
