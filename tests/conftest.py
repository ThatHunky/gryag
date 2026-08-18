import pytest_asyncio

from gryag import store


@pytest_asyncio.fixture
async def db(tmp_path):
    conn = await store.connect(str(tmp_path / "test.db"))
    yield conn
    await conn.close()
