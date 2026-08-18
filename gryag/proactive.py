"""Speaking into a silence.

Every other path in the bot starts from an incoming message. This one cannot: by
definition nothing is arriving. So it runs on a loop of its own and asks, every few
minutes, whether any chat has gone quiet long enough to be worth breaking.

Measured on the real chat, this will fire almost only in the morning — two days held just
18 gaps longer than fifteen minutes against a median gap of six seconds.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiosqlite

from gryag import config, context, gate, llm, store

log = logging.getLogger(__name__)

TICK_SECONDS = 600

PROMPT_SUFFIX = (
    "---\n"
    "Чат мовчить уже досить довго. Скажи щось сам — коротко, у своєму дусі. "
    "Можеш зачепити те, про що говорили востаннє, або просто вкинути щось своє. "
    "Не вітайся і не питай «як справи»."
)


async def _decide(db: aiosqlite.Connection, chat_id: int, now: datetime) -> gate.GateDecision:
    from gryag.handlers import _local_hour, _since

    last = await store.last_message_ts(db, chat_id)
    return gate.should_start_talking(
        gate.ProactiveInput(
            chat_enabled=True,
            chat_muted=bool(
                await store.muted_until(db, chat_id, now.isoformat(timespec="seconds"))
            ),
            local_hour=_local_hour(),
            quiet_from=await config.get_int(db, "quiet_from", chat_id),
            quiet_to=await config.get_int(db, "quiet_to", chat_id),
            silent_seconds=await _since(last),
            silence_needed=await config.get_int(db, "proactive_silence", chat_id),
            seconds_since_proactive=await _since(await store.last_proactive_ts(db, chat_id)),
            proactive_cooldown=await config.get_int(db, "proactive_cooldown", chat_id),
            has_context=last is not None,
        )
    )


async def run_once(db: aiosqlite.Connection, client, bot, persona) -> int:
    """Returns how many chats were spoken into."""
    spoken = 0
    now = datetime.now(timezone.utc)
    for chat_id in await store.enabled_chats(db):
        if await config.get(db, "proactive_enabled", chat_id) != "1":
            continue
        decision = await _decide(db, chat_id, now)
        if not decision.speak:
            log.debug("not speaking into %s: %s", chat_id, decision.reason)
            continue

        messages = await store.recent_messages(
            db, chat_id, limit=await config.get_int(db, "context_messages", chat_id)
        )
        prompt = context.build(
            messages=messages,
            chain=[],
            trigger={"text": "", "alias": "", "is_bot": False, "message_id": None},
            now=now.strftime("%Y-%m-%d %H:%M"),
            chat_title="",
            week_summary=await store.latest_summary(db, chat_id, "week"),
            today_summary=await store.latest_summary(db, chat_id, "day"),
        ).rsplit("---", 1)[0] + PROMPT_SUFFIX

        model = await config.get(db, "speak_model", chat_id)
        result = await llm.generate(
            client,
            model=model,
            system=persona["text"] if isinstance(persona, dict) else persona,
            user=prompt,
            max_output_tokens=await config.get_int(db, "max_output_tokens", chat_id),
            thinking_budget=await config.get_int(db, "thinking_budget", chat_id),
            use_tools=await config.get(db, "tools_enabled", chat_id) == "1",
        )
        if result is None:
            continue

        sent = await bot.send_message(chat_id, result.text)
        await store.save_message(
            db,
            chat_id=chat_id,
            message_id=sent.message_id,
            user_id=sent.from_user.id if sent.from_user else None,
            ts=sent.date.isoformat(timespec="seconds"),
            text=result.text,
            media_kind=None,
            file_id=None,
            reply_to=None,
            is_bot=True,
        )
        await store.mark_proactive(db, chat_id, now.isoformat(timespec="seconds"))
        await store.record_usage(
            db,
            chat_id=chat_id,
            purpose="proactive",
            model=model,
            prompt_tok=result.prompt_tokens,
            cached_tok=result.cached_tokens,
            visible_tok=result.visible_tokens,
            thought_tok=result.thought_tokens,
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
            searched=result.searched,
        )
        log.info("spoke into the silence in %s", chat_id)
        spoken += 1
    return spoken


async def loop(db: aiosqlite.Connection, client, bot, persona) -> None:
    while True:
        try:
            await run_once(db, client, bot, persona)
        except Exception:
            log.exception("proactive pass failed")
        await asyncio.sleep(TICK_SECONDS)
