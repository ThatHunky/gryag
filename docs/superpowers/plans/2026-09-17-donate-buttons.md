# «Підтримати бота» Donate Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a «🫙 Підтримати бота» / «💳 Картка» button row under the key messages of gryag and pisun-bot, and add `/donate` to both.

**Architecture:** One small, DB-free `donate` module per bot builds the keyboard and the `/donate` text from env vars. Call sites opt in explicitly — no send-path interception. In pisun-bot the old random text footer «Підтримай пісюн-бота» (jar `77iG8mGBsH`) and its weekly boost are removed and replaced by these buttons.

**Tech Stack:** Python 3, aiogram 3.30 (gryag, SQLite, pytest `asyncio_mode=auto`), aiogram 3.17 (pisun-bot, Postgres, pytest + unittest). Both have `aiogram.types.CopyTextButton`.

**Spec:** `docs/superpowers/specs/2026-09-17-donate-buttons-design.md` (same file in both repos).

**User decisions (already made):**
- Buttons under a message, not a text footer.
- Only “hero” messages: gryag `/pidor` verdict and `/pidrahuika`; pisun-bot `/pisun` results, `/top`, `/top_week`, world-boss kill.
- Jar `https://send.monobank.ua/jar/3KMKUPJ4TP`, card `4874 1000 3199 9561`, same for both bots.
- dobrovolskyi.com.ua appears only in `/donate`.
- Button label «Підтримати бота».
- The ЗСУ footer in pisun-bot (`src/zsu_donation.py`, `/adm_donation_zsu`, `/donation_group`) is a different thing and is NOT touched.
- pisun-bot's old «Підтримай пісюн-бота» text footer is replaced by the buttons (removed, with its boost scheduler).
- No per-chat off switch in pisun-bot for now.

**Interpretation recorded here:** on gryag `/pidor` the buttons go under the final VERDICT message (which both the command and the daily auto-roll send), not under the warm-up lines and not under the «already chosen today» repeat, which fires on every re-run.

---

## File map

**gryag-v2** (`/home/thathunky/bots/gryag-v2`)
- Create `gryag/donate.py` — keyboard builders, `/donate` text, `/donate` router.
- Create `tests/test_donate.py`.
- Modify `gryag/handlers.py:226-229` — `answer()` forwards `parse_mode` / `reply_markup`.
- Modify `tests/conftest.py:64-69` — `FakeMessage.reply` accepts and records them.
- Modify `gryag/pidor.py:97-133` — `_say()` takes `reply_markup`; verdict passes the keyboard.
- Modify `gryag/pidrahuika.py:227, 264, 271` — command replies and morning post carry the keyboard.
- Modify `gryag/__main__.py:100-120` — BotCommand + router.
- Modify `.env` — three `DONATE_*` vars (not committed).

**pisun-bot** (`/home/thathunky/bots/pisun-bot`)
- Create `src/donate.py`, `tests/test_donate.py`.
- Modify `src/utils.py:1058-1105` — delete the old footer.
- Modify `src/scheduler.py:47, 136-143, 387-427` — delete the boost jobs.
- Modify `src/handlers/common.py:176-181` — `_expire_markup_after(..., keep=)`.
- Modify `src/handlers/progression.py` — `/pisun` and reroll-confirm.
- Modify `src/handlers/inline.py` — inline `/pisun`, inline reroll, and drop the footer at 4 other sites.
- Modify `src/handlers/leaderboards.py` — `/top`, `/top_week`.
- Modify `src/services/boss_service.py:850, 1057, 1745-1796` — kill broadcasts.
- Modify `src/handlers/meta.py`, `src/bot_commands.py` — `/donate`.
- Modify `tests/test_handlers_inline.py` — drop 6 `maybe_donation_footer` patches.
- Modify `.env` — three `DONATE_*` vars (not committed).

pisun-bot tests that touch the DB need the throwaway Postgres from its CLAUDE.md. Everything marked "no DB" runs with a bare `.venv/bin/python -m pytest`. **Never point tests at `pisun-bot-db-1`.**

```bash
docker run -d --rm --name pisun-test-pg -e POSTGRES_PASSWORD=testpass -e POSTGRES_USER=testuser -e POSTGRES_DB=pisun_bot_test -p 127.0.0.1:55433:5432 postgres:16-alpine
```
DB-backed prefix used below as `PGENV`:
`env DB_HOST=127.0.0.1 DB_PORT=55433 DB_USER=testuser DB_PASS=testpass DB_NAME=pisun_bot_test`

---

### Task 1: gryag `donate` module

**Goal:** A DB-free module that builds the donate keyboard and the `/donate` text from env vars.

**Files:**
- Create: `gryag/donate.py`
- Test: `tests/test_donate.py`

**Acceptance Criteria:**
- [ ] `donate_keyboard()` returns one row: url button «🫙 Підтримати бота» → `DONATE_JAR_URL`, copy button «💳 Картка» → `DONATE_CARD`.
- [ ] Missing card → only jar button; missing jar → only card button; both missing → `None`.
- [ ] `with_donate_row(markup)` appends the row after existing rows without changing them; with no env returns `markup` unchanged (including `None`).
- [ ] `donate_text()` HTML-escapes values, shows the site only when `DONATE_SITE_URL` is set, returns `None` with neither jar nor card.

**Verify:** `cd /home/thathunky/bots/gryag-v2 && .venv/bin/python -m pytest tests/test_donate.py tests/test_lint.py` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** — `tests/test_donate.py`:

```python
import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from gryag import donate

JAR = "https://send.monobank.ua/jar/3KMKUPJ4TP"
CARD = "4874 1000 3199 9561"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("DONATE_JAR_URL", "DONATE_CARD", "DONATE_SITE_URL"):
        monkeypatch.delenv(name, raising=False)


def _configure(monkeypatch, jar=JAR, card=CARD, site=None):
    if jar is not None:
        monkeypatch.setenv("DONATE_JAR_URL", jar)
    if card is not None:
        monkeypatch.setenv("DONATE_CARD", card)
    if site is not None:
        monkeypatch.setenv("DONATE_SITE_URL", site)


def test_the_keyboard_is_the_jar_and_a_card_that_copies(monkeypatch):
    _configure(monkeypatch)

    (row,) = donate.donate_keyboard().inline_keyboard

    jar, card = row
    assert jar.text == "🫙 Підтримати бота"
    assert jar.url == JAR
    assert card.text == "💳 Картка"
    assert card.copy_text.text == CARD


def test_without_a_card_only_the_jar_is_offered(monkeypatch):
    _configure(monkeypatch, card=None)

    (row,) = donate.donate_keyboard().inline_keyboard

    assert [b.url for b in row] == [JAR]


def test_without_a_jar_only_the_card_is_offered(monkeypatch):
    _configure(monkeypatch, jar=None)

    (row,) = donate.donate_keyboard().inline_keyboard

    assert [b.copy_text.text for b in row] == [CARD]


def test_with_nothing_configured_there_is_no_keyboard():
    assert donate.donate_keyboard() is None


def test_blank_values_count_as_nothing(monkeypatch):
    _configure(monkeypatch, jar="  ", card="")

    assert donate.donate_keyboard() is None


def test_the_row_goes_under_existing_buttons_without_touching_them(monkeypatch):
    _configure(monkeypatch)
    game = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="гра", callback_data="g")]]
    )

    merged = donate.with_donate_row(game)

    assert merged.inline_keyboard[0][0].callback_data == "g"
    assert merged.inline_keyboard[1][0].url == JAR
    assert len(game.inline_keyboard) == 1


def test_with_nothing_configured_the_markup_is_returned_as_is():
    game = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="гра", callback_data="g")]]
    )

    assert donate.with_donate_row(game) is game
    assert donate.with_donate_row(None) is None


def test_the_text_carries_the_jar_the_card_and_the_site(monkeypatch):
    _configure(monkeypatch, site="https://dobrovolskyi.com.ua")

    text = donate.donate_text()

    assert JAR in text
    assert f"<code>{CARD}</code>" in text
    assert "https://dobrovolskyi.com.ua" in text


def test_the_text_leaves_the_site_out_when_there_is_none(monkeypatch):
    _configure(monkeypatch)

    assert "dobrovolskyi" not in donate.donate_text()


def test_the_text_escapes_what_it_is_given(monkeypatch):
    _configure(monkeypatch, card="<b>1</b>")

    assert "&lt;b&gt;1&lt;/b&gt;" in donate.donate_text()


def test_with_nothing_configured_there_is_no_text():
    assert donate.donate_text() is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_donate.py`
Expected: FAIL — `ImportError: cannot import name 'donate'`

- [ ] **Step 3: Implement** — `gryag/donate.py`:

```python
"""«Підтримати бота»: the donate buttons and the /donate text.

The details live in the environment, not in the config table: they are the same for
every chat, and the admin menu has no business editing a card number. They are read at
call time rather than at import, so a test can set them and a restart picks up an edit.
"""

from __future__ import annotations

import html
import os

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _row() -> list[InlineKeyboardButton]:
    row = []
    if jar := _env("DONATE_JAR_URL"):
        row.append(InlineKeyboardButton(text="🫙 Підтримати бота", url=jar))
    if card := _env("DONATE_CARD"):
        # copy_text rather than a callback: one tap puts the number on the clipboard,
        # which is the whole reason anybody presses it.
        row.append(InlineKeyboardButton(text="💳 Картка", copy_text=CopyTextButton(text=card)))
    return row


def donate_keyboard() -> InlineKeyboardMarkup | None:
    row = _row()
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def with_donate_row(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """`markup` with the donate row underneath, leaving the original untouched."""
    row = _row()
    if not row:
        return markup
    rows = [list(r) for r in markup.inline_keyboard] if markup else []
    return InlineKeyboardMarkup(inline_keyboard=[*rows, row])


def donate_text() -> str | None:
    jar, card, site = _env("DONATE_JAR_URL"), _env("DONATE_CARD"), _env("DONATE_SITE_URL")
    if not jar and not card:
        return None
    lines = ["💛 <b>Підтримати бота</b>", "", "Донати йдуть на сервер і розвиток ботів.", ""]
    if jar:
        lines.append(f'🫙 <a href="{html.escape(jar, quote=True)}">Банка</a>')
    if card:
        lines.append(f"💳 Картка: <code>{html.escape(card)}</code>")
    if site:
        label = site.split("://", 1)[-1].rstrip("/")
        lines.append(f'🌐 <a href="{html.escape(site, quote=True)}">{html.escape(label)}</a>')
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_donate.py tests/test_lint.py`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add gryag/donate.py tests/test_donate.py
git commit -m "feat: build the «Підтримати бота» keyboard from the environment"
```

---

### Task 2: gryag `/donate` command

**Goal:** `/donate` answers with the full details in any chat, and `answer()` can carry markup.

**Files:**
- Modify: `gryag/handlers.py:226-229`
- Modify: `tests/conftest.py` (`FakeMessage.__init__`, `FakeMessage.reply`)
- Modify: `gryag/donate.py` (append command + router)
- Modify: `gryag/__main__.py:100-120`
- Test: `tests/test_donate.py`

**Acceptance Criteria:**
- [ ] `/donate` replies with `donate_text()` as HTML and the donate keyboard.
- [ ] With no env it replies «реквізитів поки немає» (not silence).
- [ ] The reply is stored as a bot message; a replayed (stale) command gets no answer.
- [ ] Works in a chat that was never switched on.
- [ ] `donate` appears in `set_my_commands`; the router is included before `handlers.build_router()`.

**Verify:** `.venv/bin/python -m pytest` → whole suite passes

**Steps:**

- [ ] **Step 1: Write failing tests** — append to `tests/test_donate.py`:

```python
from datetime import datetime, timedelta, timezone


async def test_the_command_answers_with_the_details_and_the_buttons(db, monkeypatch):
    from tests.conftest import FakeMessage

    _configure(monkeypatch, site="https://dobrovolskyi.com.ua")
    message = FakeMessage(text="/donate")

    await donate.show_command(message, db)

    assert CARD in message.replies[0]
    assert message.parse_modes[0] == "HTML"
    assert message.markups[0].inline_keyboard[0][0].url == JAR


async def test_the_command_says_so_when_nothing_is_configured(db):
    from tests.conftest import FakeMessage

    message = FakeMessage(text="/donate")

    await donate.show_command(message, db)

    assert message.replies == ["реквізитів поки немає"]


async def test_the_commands_answer_is_stored(db, monkeypatch):
    from tests.conftest import FakeMessage

    _configure(monkeypatch)

    await donate.show_command(FakeMessage(text="/donate"), db)

    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_bot = 1", (-100,)
    ) as cur:
        assert (await cur.fetchone())[0] == 1


async def test_a_replayed_command_is_not_answered(db, monkeypatch):
    from tests.conftest import FakeMessage

    _configure(monkeypatch)
    message = FakeMessage(text="/donate", date=datetime.now(timezone.utc) - timedelta(hours=3))

    await donate.show_command(message, db)

    assert message.replies == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_donate.py`
Expected: FAIL — `AttributeError: module 'gryag.donate' has no attribute 'show_command'`

- [ ] **Step 3: Let `answer()` carry markup** — `gryag/handlers.py:226-229` becomes:

```python
async def answer(
    message, db, text: str, *, parse_mode: str | None = None, reply_markup=None
) -> None:
    """Reply to a command, and store the reply like anything else the bot says."""
    sent = await message.reply(text, parse_mode=parse_mode, reply_markup=reply_markup)
    await persist(db, sent, is_bot=True)
```

- [ ] **Step 4: Teach the fake** — in `tests/conftest.py`, add after `self.documents: ...` in `FakeMessage.__init__`:

```python
        self.parse_modes: list[str | None] = []
        self.markups: list = []
```

and replace `reply`:

```python
    async def reply(self, text, parse_mode=None, reply_markup=None):
        """The bot always answers as a Telegram reply, quoting what triggered it."""
        self.replies.append(text)
        self.parse_modes.append(parse_mode)
        self.markups.append(reply_markup)
        sent = FakeMessage(text=text, message_id=self.message_id + 1000, is_bot=True)
        sent.reply_to_message = self
        return sent
```

- [ ] **Step 5: Add the command** — append to `gryag/donate.py`, and add imports at the top (`from aiogram import Router`, `from aiogram.filters import Command`, `from aiogram.types import Message`, `from gryag import handlers`):

```python
async def show_command(message: Message, db) -> None:
    """`/donate`. Answered everywhere, like every other typed command: see accept_command."""
    if not await handlers.accept_command(message, db):
        return
    text = donate_text()
    if text is None:
        await handlers.answer(message, db, "реквізитів поки немає")
        return
    await handlers.answer(
        message, db, text, parse_mode="HTML", reply_markup=donate_keyboard()
    )


def build_router() -> Router:
    router = Router(name="donate")
    router.message(Command("donate"))(show_command)
    return router
```

Check `gryag/handlers.py` does not import `donate`/`pidor`/`pidrahuika` (it does not today), so no cycle.

- [ ] **Step 6: Wire it** — `gryag/__main__.py`: add `from gryag import donate` next to the other `gryag` imports (keep the existing import style of that file); add to `set_my_commands` after the `lore` entry:

```python
        BotCommand(command="donate", description="підтримати бота"),
```

and after `dispatcher.include_router(lore.build_router())`:

```python
    dispatcher.include_router(donate.build_router())
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/bin/python -m pytest`
Expected: all pass (the conftest change is backward compatible: existing callers pass only `text`).

- [ ] **Step 8: Commit**

```bash
git add gryag/donate.py gryag/handlers.py gryag/__main__.py tests/conftest.py tests/test_donate.py
git commit -m "feat: /donate, with the jar, the card and the site"
```

---

### Task 3: gryag buttons under `/pidor` and `/pidrahuika`

**Goal:** The pidor verdict and every pidrahuika board message carry the donate keyboard.

**Files:**
- Modify: `gryag/pidor.py:97-133`
- Modify: `gryag/pidrahuika.py:227, 264, 271`
- Test: `tests/test_pidor.py`, `tests/test_pidrahuika.py`

**Acceptance Criteria:**
- [ ] A new-winner announcement: the VERDICT message has the donate keyboard; both warm-up messages have none.
- [ ] The «already chosen» repeat has no keyboard.
- [ ] `/pidrahuika` answers (fresh and cached) have the keyboard; «табло не відповідає» has none.
- [ ] The morning post (`post_due`) has the keyboard.
- [ ] With no env, nothing gets a keyboard and nothing breaks.

**Verify:** `.venv/bin/python -m pytest tests/test_pidor.py tests/test_pidrahuika.py` → all pass

**Steps:**

- [ ] **Step 1: Write failing tests** — append to `tests/test_pidor.py`:

```python
class MarkupBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.markups: list = []

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None, **kwargs):
        self.markups.append(reply_markup)
        return await super().send_message(chat_id, text, parse_mode=parse_mode)


async def test_only_the_verdict_carries_the_donate_buttons(db, monkeypatch):
    monkeypatch.setenv("DONATE_JAR_URL", "https://send.monobank.ua/jar/3KMKUPJ4TP")
    await _populate(db)
    bot = MarkupBot()

    await pidor.announce(bot, db, -100, 3, True, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    warmup_1, warmup_2, verdict = bot.markups
    assert warmup_1 is None and warmup_2 is None
    assert verdict.inline_keyboard[0][0].url == "https://send.monobank.ua/jar/3KMKUPJ4TP"


async def test_a_repeat_of_todays_winner_has_no_buttons(db, monkeypatch):
    monkeypatch.setenv("DONATE_JAR_URL", "https://send.monobank.ua/jar/3KMKUPJ4TP")
    await _populate(db)
    bot = MarkupBot()

    await pidor.announce(bot, db, -100, 3, False, datetime(2026, 8, 19, 12, tzinfo=timezone.utc))

    assert bot.markups == [None]
```

Append to `tests/test_pidrahuika.py`:

```python
async def test_the_command_carries_the_donate_buttons_fresh_and_cached(db, _board, monkeypatch):
    from tests.conftest import FakeMessage

    monkeypatch.setenv("DONATE_JAR_URL", "https://send.monobank.ua/jar/3KMKUPJ4TP")
    pidrahuika._last_asked.clear()
    first, second = FakeMessage(text="/pidrahuika"), FakeMessage(text="/pidrahuika")

    await pidrahuika.show_command(first, db)
    await pidrahuika.show_command(second, db)

    assert first.markups[0].inline_keyboard[0][0].url.endswith("3KMKUPJ4TP")
    assert second.markups[0].inline_keyboard[0][0].url.endswith("3KMKUPJ4TP")


async def test_a_board_that_does_not_answer_gets_no_buttons(db, monkeypatch):
    from tests.conftest import FakeMessage

    monkeypatch.setenv("DONATE_JAR_URL", "https://send.monobank.ua/jar/3KMKUPJ4TP")
    pidrahuika._last_asked.clear()

    async def no_answer(period_type, now=None):
        return None

    monkeypatch.setattr(pidrahuika, "fetch_report", no_answer)
    message = FakeMessage(text="/pidrahuika")

    await pidrahuika.show_command(message, db)

    assert message.replies == ["табло не відповідає"]
    assert message.markups == [None]
```

and, for the morning post (`FakeBot.send_message` there already takes `**kwargs`):

```python
class MarkupBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.markups: list = []

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.markups.append(reply_markup)
        return await super().send_message(chat_id, text, **kwargs)


async def test_the_morning_post_carries_the_donate_buttons(db, _board, monkeypatch):
    monkeypatch.setenv("DONATE_JAR_URL", "https://send.monobank.ua/jar/3KMKUPJ4TP")
    await admin.enable_chat(db, -100, "матсурі")
    await config.set(db, "pidrahuika_enabled", "1", chat_id=-100)
    bot = MarkupBot()

    assert await pidrahuika.post_due(db, bot, datetime(2026, 8, 19, 6, 30, tzinfo=timezone.utc)) == 1
    assert bot.markups[0].inline_keyboard[0][0].url.endswith("3KMKUPJ4TP")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_pidor.py tests/test_pidrahuika.py`
Expected: the new tests FAIL (markups are `None` / `KeyError: 'reply_markup'`).

- [ ] **Step 3: Implement pidor** — `gryag/pidor.py`: add `donate` to `from gryag import config, handlers, phrases, store` (→ `config, donate, handlers, phrases, store`). Change `_say`'s signature and send:

```python
async def _say(
    bot, db, chat_id: int, text: str, parse_mode: str | None = None, reply_markup=None
) -> None:
    sent = await bot.send_message(
        chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup
    )
```

and the verdict line in `announce`:

```python
    await _say(
        bot,
        db,
        chat_id,
        phrases.pick(phrases.VERDICT, seed).format(who=who),
        "HTML",
        reply_markup=donate.donate_keyboard(),
    )
```

The existing `FakeBot.send_message(self, chat_id, text, parse_mode=None, **kwargs)` already swallows `reply_markup`, so old tests keep passing.

- [ ] **Step 4: Implement pidrahuika** — `gryag/pidrahuika.py`: add `donate` to the `from gryag import ...` line. Line 227:

```python
            sent = await bot.send_message(chat_id, text, reply_markup=donate.donate_keyboard())
```

In `show_command`, the cached answer and the final answer:

```python
        await handlers.answer(message, db, cached[1], reply_markup=donate.donate_keyboard())
```

```python
    await handlers.answer(message, db, text, reply_markup=donate.donate_keyboard())
```

Leave «табло не відповідає» as is.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add gryag/pidor.py gryag/pidrahuika.py tests/test_pidor.py tests/test_pidrahuika.py
git commit -m "feat: the donate buttons under the pidor verdict and the killboard"
```

---

### Task 4: pisun-bot `donate` module and `/donate`

**Goal:** The same DB-free module in pisun-bot, plus `/donate`, the menu entry and a help line.

**Files:**
- Create: `src/donate.py`
- Create: `tests/test_donate.py`
- Modify: `src/handlers/meta.py` (new handler after `cmd_help`; one help line)
- Modify: `src/bot_commands.py`

**Acceptance Criteria:**
- [ ] Same keyboard/text behaviour as Task 1 (identical tests pass).
- [ ] `/donate` replies HTML text + keyboard; with no env replies «реквізитів поки немає».
- [ ] `donate` is in `set_bot_commands`; `/help` lists `/donate`.

**Verify:** `cd /home/thathunky/bots/pisun-bot && .venv/bin/python -m pytest tests/test_donate.py tests/test_debloat_visibility.py -q` → pass (no DB)

**Steps:**

- [ ] **Step 1: Write failing tests** — `tests/test_donate.py`: copy the Task 1 test file verbatim with `from gryag import donate` replaced by `from src import donate`, then append:

```python
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.handlers import meta


class _Message:
    def __init__(self):
        self.chat = SimpleNamespace(id=-100, type="group", title="t")
        self.from_user = SimpleNamespace(id=1, full_name="u")
        self.replies = []

    async def reply(self, text, **kwargs):
        self.replies.append((text, kwargs))


def test_the_command_answers_with_the_details_and_the_buttons(monkeypatch):
    _configure(monkeypatch, site="https://dobrovolskyi.com.ua")
    message = _Message()

    with patch("src.handlers.meta._register_message_chat", AsyncMock()):
        asyncio.run(meta.cmd_donate(message))

    text, kwargs = message.replies[0]
    assert CARD in text
    assert kwargs["parse_mode"] == "HTML"
    assert kwargs["reply_markup"].inline_keyboard[0][0].url == JAR


def test_the_command_says_so_when_nothing_is_configured():
    message = _Message()

    with patch("src.handlers.meta._register_message_chat", AsyncMock()):
        asyncio.run(meta.cmd_donate(message))

    assert message.replies[0][0] == "реквізитів поки немає"


def test_donate_is_in_the_command_menu():
    from src.bot_commands import set_bot_commands

    bot = SimpleNamespace(commands=[])

    async def set_my_commands(commands):
        bot.commands = commands

    bot.set_my_commands = set_my_commands
    asyncio.run(set_bot_commands(bot))

    assert "donate" in {c.command for c in bot.commands}
```

The Task 1 tests are sync (`def`), so they run without pytest-asyncio.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_donate.py -q`
Expected: FAIL — `ImportError: cannot import name 'donate' from 'src'`

- [ ] **Step 3: Implement** — `src/donate.py`: copy `gryag/donate.py` from Task 1 **Step 3 only** (keyboard + text, no router, no `handlers` import), keeping its docstring but ending the first paragraph at "...editing a card number." In `src/handlers/meta.py` add `from src.donate import donate_keyboard, donate_text` to the imports, and after `cmd_help`:

```python
@router.message(Command("donate"))
async def cmd_donate(message: Message):
    await _register_message_chat(message)
    text = donate_text()
    if text is None:
        await message.reply("реквізитів поки немає")
        return
    await message.reply(
        text,
        parse_mode="HTML",
        reply_markup=donate_keyboard(),
        disable_web_page_preview=True,
    )
```

In `cmd_help`, add this line immediately before `"⚙️ <b>Налаштування (адмін чату)</b>\n"`:

```python
        "💛 /donate — підтримати бота\n\n"
```

In `src/bot_commands.py`, before the `help` entry:

```python
        BotCommand(command="donate", description="Підтримати бота"),
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_donate.py tests/test_debloat_visibility.py -q`
Expected: pass

- [ ] **Step 5: Commit**

```bash
git add src/donate.py src/handlers/meta.py src/bot_commands.py tests/test_donate.py
git commit -m "feat: /donate and the «Підтримати бота» keyboard"
```

---

### Task 5: pisun-bot — replace the old footer with buttons on `/pisun` results

**Goal:** Remove «Підтримай пісюн-бота» (footer, boost, scheduler jobs) and put the donate keyboard on every `/pisun` result: command, reroll-confirm, inline, inline reroll.

**Files:**
- Modify: `src/utils.py:1058-1105`
- Modify: `src/scheduler.py:47, 136-143, 387-427`
- Modify: `src/handlers/common.py:176-181`
- Modify: `src/handlers/progression.py:48, 996-1006, 1046-1059`
- Modify: `src/handlers/inline.py:70, 1404, 2121, 2244, 2309, 2405, 2745`
- Modify: `tests/test_handlers_inline.py` (6 patches)
- Test: `tests/test_donate.py`

**Acceptance Criteria:**
- [ ] `grep -rn "maybe_donation_footer\|DONATION_FOOTERS\|set_donation_boost\|donation_boost\|77iG8mGBsH" src tests` → no output.
- [ ] `/pisun` success reply has game buttons (if any) followed by the donate row; after 30 s the game buttons go and the donate row stays.
- [ ] A `/pisun` success with no game buttons still gets the donate row and schedules no expiry.
- [ ] Inline `/pisun` and inline reroll results end with the donate keyboard (or the empty keyboard with no env).
- [ ] Slots, gift, claimed-gift and solo-shop inline results are sent as before minus the footer.
- [ ] ЗСУ footer code untouched: `git diff --stat` shows no change in `src/zsu_donation.py`, `src/pisun_bot.py`.

**Verify:** `.venv/bin/python -m pytest tests/test_donate.py tests/test_debloat_visibility.py tests/test_daily_roll_lock.py -q` (no DB) and `PGENV .venv/bin/python -m pytest tests/test_handlers_inline.py tests/test_scheduler.py -q` → pass

**Steps:**

- [ ] **Step 1: Write failing tests** — append to `tests/test_donate.py`:

```python
import datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.handlers import common, progression


class _PisunMessage(_Message):
    def __init__(self):
        super().__init__()
        self.from_user = SimpleNamespace(id=42, full_name="User")
        self.bot = SimpleNamespace()

    async def reply(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(message_id=len(self.replies))


def _profile():
    return SimpleNamespace(
        current_streak=0, last_measure=None, length=10.0, measure_count=1,
        weekly_length=1.0, last_reset_week="2026-W1", pisun_name=None,
    )


def _run_pisun(message, has_double):
    fake_db = SimpleNamespace(progression=SimpleNamespace(
        get_user_profile=AsyncMock(side_effect=[_profile(), _profile()]),
        get_global_last_measure=AsyncMock(return_value=None),
    ))
    spawned = []

    def fake_create_task(coro):
        spawned.append(coro)
        coro.close()

    async def run():
        with patch("src.handlers.progression.db", fake_db), \
             patch("src.handlers.progression._register_message_chat", AsyncMock()), \
             patch("src.handlers.progression.get_roll_day_now", return_value=datetime.datetime(2026, 1, 5, 12, 0)), \
             patch("src.handlers.progression.asyncio.create_task", side_effect=fake_create_task), \
             patch("src.handlers.progression._execute_measurement", AsyncMock(return_value=("ok", 2.0, 12.0, has_double))):
            await progression.cmd_pisun(message)

    asyncio.run(run())
    return spawned


def test_a_pisun_result_ends_with_the_donate_row_under_the_game_buttons(monkeypatch):
    _configure(monkeypatch)
    message = _PisunMessage()

    spawned = _run_pisun(message, has_double=True)

    text, kwargs = message.replies[-1]
    rows = kwargs["reply_markup"].inline_keyboard
    assert "dbl:" in repr(rows[0])
    assert rows[-1][0].url == JAR
    assert "Підтримай пісюн-бота" not in text
    assert len(spawned) == 1


def test_a_pisun_result_without_game_buttons_still_gets_the_row_and_no_expiry(monkeypatch):
    _configure(monkeypatch)
    message = _PisunMessage()

    spawned = _run_pisun(message, has_double=False)

    (row,) = message.replies[-1][1]["reply_markup"].inline_keyboard
    assert row[0].url == JAR
    assert spawned == []


def test_expiring_game_buttons_can_leave_the_donate_row_behind():
    kept = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="x", url=JAR)]])
    message = SimpleNamespace(edit_reply_markup=AsyncMock())

    asyncio.run(common._expire_markup_after(message, delay=0, keep=kept))

    message.edit_reply_markup.assert_awaited_once_with(reply_markup=kept)
```

`test_debloat_visibility.py` already relies on the `dbl:` button rendering with `has_double=True` (inventory is live), and on the gamble and robbery buttons staying hidden.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_donate.py -q`
Expected: the three new tests FAIL (no donate row; `_expire_markup_after() got an unexpected keyword argument 'keep'`).

- [ ] **Step 3: `common._expire_markup_after`** — replace lines 176-181:

```python
async def _expire_markup_after(
    message: Message, delay: int = 30, keep: Optional[InlineKeyboardMarkup] = None
):
    """Drop a message's short-lived buttons after `delay`, leaving `keep` in their place."""
    await asyncio.sleep(delay)
    try:
        await message.edit_reply_markup(reply_markup=keep)
    except TelegramBadRequest:
        pass
```

`common.py` already imports `Optional` and `InlineKeyboardMarkup`.

- [ ] **Step 4: `progression.py`** — remove `maybe_donation_footer,` from the `src.utils` import; add `from src.donate import donate_keyboard, with_donate_row`. Replace lines 996-1006:

```python
    game_kb = _double_keyboard(delta, user_id) if has_double and not is_feature_paused("inventory") else None
    game_kb = append_gamble_button(game_kb, delta, user_id)
    game_kb = append_robbery_button(game_kb, delta, user_data.current_streak if user_data else 0, new_length)

    msg = await message.reply(
        reply_text, reply_markup=with_donate_row(game_kb), parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if game_kb:
        asyncio.create_task(_expire_markup_after(msg, keep=donate_keyboard()))
```

Replace the reroll-confirm tail (lines 1046-1059):

```python
    game_kb = _double_keyboard(delta, user_id) if has_double else None
    game_kb = append_gamble_button(game_kb, delta, user_id)
    game_kb = append_robbery_button(game_kb, delta, user_data.current_streak if user_data else 0, new_length)

    edited_text = f"🎲 <b>Перекидання</b> використано!\n\n{reply_text}"
    await query.message.edit_text(
        edited_text,
        parse_mode="HTML",
        reply_markup=with_donate_row(game_kb),
    )
    if game_kb:
        asyncio.create_task(_expire_markup_after(query.message, keep=donate_keyboard()))
    await query.answer()
```

- [ ] **Step 5: `inline.py`** — remove `maybe_donation_footer,` from the `src.utils` import; add `from src.donate import donate_keyboard`. At each site:

Line ~2121 (inline `/pisun`):
```python
    await bot.edit_message_text(
        inline_message_id=inline_message_id,
        text=base_text,
        parse_mode="HTML",
        # The empty keyboard is what clears the loading button when nothing is configured.
        reply_markup=donate_keyboard() or _EMPTY_KEYBOARD,
        disable_web_page_preview=True,
    )
```
Line ~2745 (inline reroll): same, with `text=f"🎲 <i>Перекидання</i>\n\n{base_text}"` and `reply_markup=donate_keyboard() or _EMPTY_KEYBOARD`; keep its `try/except TelegramBadRequest`.
Line ~1404 (solo shop), ~2244 (slots), ~2309 (gift), ~2405 (claimed gift): delete the `x, parse_mode = maybe_donation_footer(y)` line, pass `text=y` directly (`text=text`, `text=result`, `text=text`, `text=_claimed_gift_text(gift)`) and `parse_mode="HTML"`. Check each block below the removed line for other uses of `final_text`/`parse_mode` (the claimed-gift site has an `elif message:` branch) and point them at the same expression.

- [ ] **Step 6: `utils.py`** — delete lines 1058-1105: the `# Donation footer` banner, `_DONATION_CARD`, `DONATION_FOOTERS`, `DONATION_BASE_CHANCE`, `DONATION_BOOSTED_CHANCE`, `_donation_chance`, `set_donation_boost`, `maybe_donation_footer`. Leave `MEGA_ADJECTIVES` onward.

- [ ] **Step 7: `scheduler.py`** — line 47 becomes `from src.utils import KYIV_TZ, get_kyiv_today`; delete `_activate_donation_boost` and `_deactivate_donation_boost` (136-143) and the whole `# Weekly donation-footer boost` block through the `donation_boost_reschedule` `add_job(...)` (387-427). The scheduler has no persistent jobstore, so the removed jobs simply stop existing on restart.

- [ ] **Step 8: `tests/test_handlers_inline.py`** — drop the 6 patches and dedent their bodies:

```bash
.venv/bin/python - <<'EOF'
import pathlib
p = pathlib.Path("tests/test_handlers_inline.py")
lines = p.read_text().splitlines(keepends=True)
out, i = [], 0
while i < len(lines):
    line = lines[i]
    if "maybe_donation_footer" in line and line.lstrip().startswith("with patch("):
        indent = len(line) - len(line.lstrip())
        i += 1
        while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
            out.append(lines[i][4:] if lines[i].strip() else lines[i])
            i += 1
        continue
    out.append(line)
    i += 1
p.write_text("".join(out))
EOF
git diff --stat tests/test_handlers_inline.py
```
Expected: 6 lines removed, bodies dedented; `grep -c maybe_donation_footer tests/test_handlers_inline.py` → `0`.

- [ ] **Step 9: Run**

```bash
grep -rn "maybe_donation_footer\|DONATION_FOOTERS\|set_donation_boost\|donation_boost\|77iG8mGBsH" src tests
.venv/bin/python -m pytest tests/test_donate.py tests/test_debloat_visibility.py tests/test_daily_roll_lock.py -q
env DB_HOST=127.0.0.1 DB_PORT=55433 DB_USER=testuser DB_PASS=testpass DB_NAME=pisun_bot_test .venv/bin/python -m pytest tests/test_handlers_inline.py tests/test_scheduler.py -q
```
Expected: grep prints nothing; both pytest runs pass.

- [ ] **Step 10: Commit**

```bash
git add src/utils.py src/scheduler.py src/handlers/common.py src/handlers/progression.py src/handlers/inline.py tests/test_handlers_inline.py tests/test_donate.py
git commit -m "feat: donate buttons replace the «Підтримай пісюн-бота» footer on /pisun"
```

---

### Task 6: pisun-bot buttons under `/top`, `/top_week` and the boss kill

**Goal:** Leaderboards and world-boss kill announcements carry the donate keyboard; escapes and empty leaderboards do not.

**Files:**
- Modify: `src/handlers/leaderboards.py` (`cmd_top` final reply, `cmd_top_week` final reply)
- Modify: `src/services/boss_service.py:850, 1057, 1745-1796`
- Test: `tests/test_donate.py`

**Acceptance Criteria:**
- [ ] Non-empty `/top` and `/top_week` replies have the donate keyboard; the empty-state replies do not.
- [ ] `_broadcast_settlement_message(..., reply_markup=kb)` sends `reply_markup=kb` to every card chat; default sends none.
- [ ] `_broadcast_inline_settlement_message(..., reply_markup=kb)` edits with `kb`; default edits with the empty keyboard.
- [ ] Only the two kill paths (lines ~850, ~1057) pass `donate_keyboard()`; escape paths (~966, ~1111) are unchanged.

**Verify:** `.venv/bin/python -m pytest tests/test_donate.py -q` (no DB) and `PGENV .venv/bin/python -m pytest tests/test_handlers_leaderboards.py -q` → pass

**Steps:**

- [ ] **Step 1: Write failing tests** — append to `tests/test_donate.py`:

```python
from src.handlers import leaderboards
from src.services.boss_service import BossService


def test_the_chat_top_carries_the_donate_buttons(monkeypatch):
    _configure(monkeypatch)
    message = _Message()
    entry = SimpleNamespace(
        username="u", elite_font=None, custom_emoji=None, prestige_level=0,
        current_streak=0, length=10.0, user_id=1,
    )
    fake_db = SimpleNamespace(progression=SimpleNamespace(get_top_users=AsyncMock(return_value=[entry])))

    async def run():
        with patch("src.handlers.leaderboards.db", fake_db), \
             patch("src.handlers.leaderboards._register_message_chat", AsyncMock()):
            await leaderboards.cmd_top(message)

    asyncio.run(run())

    assert message.replies[-1][1]["reply_markup"].inline_keyboard[0][0].url == JAR


def test_an_empty_chat_top_has_no_buttons(monkeypatch):
    _configure(monkeypatch)
    message = _Message()
    fake_db = SimpleNamespace(progression=SimpleNamespace(
        get_top_users=AsyncMock(return_value=[]),
        count_users_in_chat=AsyncMock(return_value=0),
    ))

    async def run():
        with patch("src.handlers.leaderboards.db", fake_db), \
             patch("src.handlers.leaderboards._register_message_chat", AsyncMock()):
            await leaderboards.cmd_top(message)

    asyncio.run(run())

    assert "reply_markup" not in message.replies[-1][1]


def _fake_boss_self(cards):
    return SimpleNamespace(
        _strip_boss_card_buttons=AsyncMock(),
        _clear_boss_state=AsyncMock(),
        _active_cards=AsyncMock(return_value=cards),
        _active_inline_cards=AsyncMock(return_value=cards),
    )


def test_a_boss_kill_broadcast_can_carry_the_buttons(monkeypatch):
    _configure(monkeypatch)
    kb = donate.donate_keyboard()
    sent = AsyncMock()
    fake_self = _fake_boss_self([SimpleNamespace(chat_id=-100)])

    async def run():
        with patch("src.services.boss_service.send_broadcast_message", sent), \
             patch("src.services.boss_service.broadcast_chat_gap_sleep", AsyncMock()):
            return await BossService._broadcast_settlement_message(fake_self, None, "b", "text", reply_markup=kb)

    assert asyncio.run(run()) is True
    assert sent.await_args.kwargs["reply_markup"] is kb


def test_an_inline_boss_kill_edit_can_carry_the_buttons(monkeypatch):
    _configure(monkeypatch)
    kb = donate.donate_keyboard()
    bot = SimpleNamespace(edit_message_text=AsyncMock())
    fake_self = _fake_boss_self([SimpleNamespace(inline_message_id="i")])

    asyncio.run(BossService._broadcast_inline_settlement_message(fake_self, bot, "b", "text", reply_markup=kb))

    assert bot.edit_message_text.await_args.kwargs["reply_markup"] is kb
```

`boss_service.py` imports `send_broadcast_message` and `broadcast_chat_gap_sleep` by name from `src.utils`, so patching them on `src.services.boss_service` is correct.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_donate.py -q`
Expected: new tests FAIL (`unexpected keyword argument 'reply_markup'`, missing markup).

- [ ] **Step 3: Leaderboards** — add `from src.donate import donate_keyboard`. Final line of `cmd_top`:

```python
    await message.reply("\n".join(lines), parse_mode="HTML", reply_markup=donate_keyboard())
```

Final line of `cmd_top_week`: identical change.

- [ ] **Step 4: Boss service** — add `from src.donate import donate_keyboard`. Signatures and sends:

```python
    async def _broadcast_settlement_message(
        self, bot: Bot, boss_id: str, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> bool:
```
```python
                await send_broadcast_message(
                    bot, card.chat_id, text, notify=True, parse_mode="HTML", reply_markup=reply_markup
                )
```
```python
    async def _broadcast_inline_settlement_message(
        self, bot: Bot, boss_id: str, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None
    ) -> bool:
```
```python
                    reply_markup=reply_markup or InlineKeyboardMarkup(inline_keyboard=[]),
```

Kill call sites only:
```python
        notified = await self._broadcast_settlement_message(bot, boss_id, message_text, reply_markup=donate_keyboard())
```
```python
        notified = await self._broadcast_inline_settlement_message(bot, boss_id, message_text, reply_markup=donate_keyboard())
```

`send_broadcast_message` forwards `**kwargs` to `send_message_with_retry`, so `reply_markup=None` is harmless.

- [ ] **Step 5: Run**

```bash
.venv/bin/python -m pytest tests/test_donate.py -q
env DB_HOST=127.0.0.1 DB_PORT=55433 DB_USER=testuser DB_PASS=testpass DB_NAME=pisun_bot_test .venv/bin/python -m pytest tests/test_handlers_leaderboards.py -q
```
Expected: pass

- [ ] **Step 6: Commit**

```bash
git add src/handlers/leaderboards.py src/services/boss_service.py tests/test_donate.py
git commit -m "feat: donate buttons under the leaderboards and a boss kill"
```

---

### Task 7: Full pisun-bot suite

**Goal:** Prove nothing else in pisun-bot broke.

**Files:** none

**Acceptance Criteria:**
- [ ] Full suite green against the throwaway Postgres (baseline 530 collected + the new tests).

**Verify:** `PGENV .venv/bin/python -m pytest tests/ -q` → `N passed`, 0 failed (≈25 min; run in background)

**Steps:**

- [ ] **Step 1:** Run the full suite with `PGENV` in the background; fix any failure caused by this work and commit the fix.
- [ ] **Step 2:** `docker rm -f pisun-test-pg`.

---

### Task 8: Configure, deploy, check live

**Goal:** Both bots run the new code with the details set, and the buttons work in Telegram.

**Files:**
- Modify: `/home/thathunky/bots/gryag-v2/.env`, `/home/thathunky/bots/pisun-bot/.env` (not committed)

**Acceptance Criteria:**
- [ ] Both `.env` files contain the three `DONATE_*` values.
- [ ] Both repos pushed to `origin/main`.
- [ ] `gryag-bot.service` active after restart; `pisun-bot-bot-1` up after rebuild; no tracebacks in the first minute of logs.
- [ ] In Telegram: `/donate` in each bot shows jar, card, site; the «Картка» button copies the number.

**Verify:** `systemctl is-active gryag-bot` → `active`; `docker compose -f /home/thathunky/bots/pisun-bot/docker-compose.yml ps bot` → `Up`

**Steps:**

- [ ] **Step 1: Env** — append to both `.env` files:

```
DONATE_JAR_URL=https://send.monobank.ua/jar/3KMKUPJ4TP
DONATE_CARD=4874 1000 3199 9561
DONATE_SITE_URL=https://dobrovolskyi.com.ua
```

- [ ] **Step 2: Push** — `git push origin main` in both repos.

- [ ] **Step 3: Deploy** — tell the user both bots are about to restart, then:

```bash
sudo systemctl restart gryag-bot
cd /home/thathunky/bots/pisun-bot && docker compose up -d --build
```

- [ ] **Step 4: Logs** — `journalctl -u gryag-bot -n 50 --no-pager` and `docker compose logs --since 2m bot`; no tracebacks.

- [ ] **Step 5: Live check** — ask the user to try `/donate` in both bots and tap «💳 Картка»; report what they see.
