import pytest
import pytest_asyncio

from gryag import store


@pytest_asyncio.fixture
async def db(tmp_path):
    conn = await store.connect(str(tmp_path / "test.db"))
    yield conn
    await conn.close()


@pytest.fixture(autouse=True)
def _clear_busy_chats():
    """The claim set is module state. A test that leaves a chat claimed would make every
    later test silently answer nothing, which is a very confusing way to fail."""
    from gryag import handlers

    handlers._busy.clear()
    handlers._pending.clear()
    handlers._tasks.clear()
    yield
    handlers._busy.clear()
    handlers._pending.clear()
    handlers._tasks.clear()
