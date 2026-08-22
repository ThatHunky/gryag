"""The admin surface sweeps itself out of the chat; conversation does not."""

import asyncio

import pytest

from gryag import cleanup


class FakeBot:
    def __init__(self):
        self.deleted = []

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeChat:
    def __init__(self, chat_id=-100):
        self.id = chat_id


class FakeMessage:
    def __init__(self, message_id=1, bot=None, chat_id=-100):
        self.message_id = message_id
        self.chat = FakeChat(chat_id)
        self.bot = bot or FakeBot()


@pytest.fixture(autouse=True)
def _no_leftover_timers():
    cleanup.cancel_all()
    yield
    cleanup.cancel_all()


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_a_swept_message_is_deleted_after_its_delay():
    bot = FakeBot()

    cleanup.sweep(bot, -100, 7, after=0)
    await _settle()

    assert bot.deleted == [(-100, 7)]


async def test_re_arming_replaces_the_pending_timer_instead_of_stacking():
    """Navigating the menu must not queue one deletion per tap."""
    bot = FakeBot()

    cleanup.sweep(bot, -100, 7, after=30)
    cleanup.sweep(bot, -100, 7, after=30)
    cleanup.sweep(bot, -100, 7, after=0)
    await _settle()

    assert bot.deleted == [(-100, 7)]


async def test_re_arming_pushes_the_deletion_back():
    bot = FakeBot()

    cleanup.sweep(bot, -100, 7, after=0)
    cleanup.sweep(bot, -100, 7, after=30)
    await _settle()

    assert bot.deleted == []


async def test_sweep_message_reads_the_ids_off_the_message():
    bot = FakeBot()

    cleanup.sweep_message(FakeMessage(message_id=42, bot=bot, chat_id=-555), after=0)
    await _settle()

    assert bot.deleted == [(-555, 42)]


async def test_sweep_message_ignores_anything_that_is_not_a_message():
    cleanup.sweep_message(None, after=0)
    cleanup.sweep_message(object(), after=0)
    await _settle()

    assert not cleanup._timers


async def test_a_failed_delete_does_not_raise_or_leak_a_timer():
    class BrokenBot(FakeBot):
        async def delete_message(self, chat_id, message_id):
            raise RuntimeError("message to delete not found")

    cleanup.sweep(BrokenBot(), -100, 7, after=0)
    await _settle()

    assert not cleanup._timers


async def test_delays_are_ordered_from_shortest_notice_to_longest_menu():
    assert cleanup.NOTICE_TTL < cleanup.REPORT_TTL < cleanup.MENU_TTL
