import types as pytypes
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from gryag import store


class FakeMessage:
    def __init__(
        self,
        *,
        text="привіт",
        message_id=1,
        chat_id=-100,
        user_id=1,
        full_name="Олег",
        is_bot=False,
        reply_to=None,
        entities=None,
        date=None,
    ):
        self.message_id = message_id
        # Telegram always sends tz-aware timestamps; the staleness guard subtracts
        # them from utcnow, so a naive datetime here would not exercise the real path.
        self.date = date or datetime.now(timezone.utc)
        self.text = text
        self.caption = None
        self.chat = pytypes.SimpleNamespace(id=chat_id, title="матсурі")
        self.from_user = pytypes.SimpleNamespace(
            id=user_id, full_name=full_name, is_bot=is_bot
        )
        self.reply_to_message = reply_to
        self.entities = entities or []
        self.photo = self.voice = self.video = None
        self.video_note = self.sticker = self.document = None
        # Service fields. Absent on an ordinary message, which is what None means here.
        self.new_chat_members = None
        self.left_chat_member = None
        self.pinned_message = None
        self.new_chat_title = None
        self.migrate_from_chat_id = None
        self.boost_added = None
        self.forum_topic_created = None
        self.forum_topic_edited = None
        self.bot = None  # disables the typing indicator; see handlers._typing
        self.replies: list[str] = []
        self.photos: list[bytes] = []

    async def reply_photo(self, photo):
        self.photos.append(photo.data)
        return FakeMessage(text="", message_id=self.message_id + 2000, is_bot=True)

    async def reply(self, text):
        """The bot always answers as a Telegram reply, quoting what triggered it."""
        self.replies.append(text)
        sent = FakeMessage(text=text, message_id=self.message_id + 1000, is_bot=True)
        sent.reply_to_message = self
        return sent


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
