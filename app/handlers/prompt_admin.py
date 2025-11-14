"""Admin commands for system prompt management."""

from __future__ import annotations

import io
import logging
from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import BotCommand, BufferedInputFile, Message

from app.config import Settings
from app.persona import SYSTEM_PERSONA
from app.services.system_prompt_manager import SystemPromptManager

router = Router()
logger = logging.getLogger(__name__)


def get_prompt_commands(prefix: str = "gryag") -> list[BotCommand]:
    """Generate prompt commands with dynamic prefix."""
    return [
        BotCommand(
            command=f"{prefix}prompt",
            description="🔒 Переглянути поточний системний промпт (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}setprompt",
            description="🔒 Встановити кастомний системний промпт (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}resetprompt",
            description="🔒 Скинути до дефолтного промпту (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}prompthistory",
            description="🔒 Показати історію версій промптів (тільки адміни)",
        ),
        BotCommand(
            command=f"{prefix}activateprompt",
            description="🔒 Активувати попередню версію промпту (тільки адміни)",
        ),
    ]


# Keep for backwards compatibility (used in main.py)
PROMPT_COMMANDS = get_prompt_commands()

# Default admin-only message - fallback when PersonaLoader is unavailable
ADMIN_ONLY = "Тільки адміни можуть це робити."


def _is_admin(user_id: int, settings: Settings) -> bool:
    """Check if user is an admin."""
    return user_id in settings.admin_user_ids_list


def _format_prompt_preview(text: str, max_length: int = 200) -> str:
    """Format prompt text for preview display."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def _format_timestamp(ts: int) -> str:
    """Format Unix timestamp to readable datetime."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


@router.message(Command(commands=["gryagprompt", "prompt"]))
async def view_prompt_command(
    message: Message,
    settings: Settings,
    prompt_manager: SystemPromptManager,
) -> None:
    """View current active system prompt.

    Usage:
        /gryagprompt - View global prompt
        /gryagprompt chat - View chat-specific prompt (if in group)
    """
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    # Parse scope from command
    scope = "global"
    chat_id_filter = None

    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].lower() == "chat":
            scope = "chat"
            chat_id_filter = message.chat.id if message.chat.id < 0 else None

    # Get active prompt
    prompt = await prompt_manager.get_active_prompt(chat_id=chat_id_filter)
    cache_label = "hit ✅" if prompt_manager.last_cache_hit else "miss ❌"

    if prompt is None:
        response = (
            f"📋 <b>Системний промпт ({scope})</b>\n\n"
            f"Статус: Використовується дефолтний промпт\n"
            f"Кеш: {cache_label}\n"
            f"Джерело: app/persona.py (SYSTEM_PERSONA)\n\n"
            f"Щоб переглянути дефолтний промпт, використайте /gryagprompt default"
        )
        await message.reply(response)
        return

    # Format response
    response = (
        f"📋 <b>Активний системний промпт</b>\n\n"
        f"Scope: {prompt.scope}\n"
        f"Chat ID: {prompt.chat_id or 'Global'}\n"
        f"Версія: v{prompt.version}\n"
        f"Створено: {_format_timestamp(prompt.created_at)}\n"
        f"Активовано: {_format_timestamp(prompt.activated_at) if prompt.activated_at else 'N/A'}\n"
        f"Адмін ID: {prompt.admin_id}\n"
        f"Кеш: {cache_label}\n"
    )

    if prompt.notes:
        response += f"Нотатки: {prompt.notes}\n"

    response += f"\n<b>Попередній перегляд:</b>\n{_format_prompt_preview(prompt.prompt_text, 300)}\n"
    response += "\n💾 Повний текст промпту надіслано файлом."

    # Send preview
    await message.reply(response)

    # Send full prompt as file
    prompt_file = BufferedInputFile(
        prompt.prompt_text.encode("utf-8"),
        filename=f"system_prompt_v{prompt.version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
    )
    await message.reply_document(
        prompt_file,
        caption=f"Повний текст системного промпту (версія {prompt.version})",
    )


# This handler checks for "default" argument and shows hardcoded prompt
@router.message(Command(commands=["gryagprompt", "prompt"]))
async def view_default_prompt_command(message: Message, settings: Settings) -> None:
    """Handle /gryagprompt default to view hardcoded prompt."""
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    if not message.text or "default" not in message.text.lower():
        return  # Let other handler process it

    response = (
        f"📋 <b>Дефолтний системний промпт</b>\n\n"
        f"Джерело: app/persona.py (SYSTEM_PERSONA)\n"
        f"Довжина: {len(SYSTEM_PERSONA)} символів\n\n"
        f"💾 Повний текст надіслано файлом."
    )

    await message.reply(response)

    # Send as file
    prompt_file = BufferedInputFile(
        SYSTEM_PERSONA.encode("utf-8"),
        filename=f"default_system_prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
    )
    await message.reply_document(
        prompt_file, caption="Дефолтний системний промпт з app/persona.py"
    )


@router.message(Command(commands=["gryagshowprompt", "showprompt"]))
async def show_effective_prompt_command(
    message: Message,
    settings: Settings,
    persona_loader: object | None = None,
    prompt_manager: SystemPromptManager | None = None,
) -> None:
    """Admin command to show the effective system prompt used by the bot.

    This shows the active prompt (DB override) if present, otherwise the
    persona loader output (from templates/YAML), otherwise the hardcoded
    `SYSTEM_PERSONA`. The full prompt is sent as a file for easy inspection.
    """
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    # Determine current time (reuse same logic as chat handler)
    try:
        from zoneinfo import ZoneInfo

        kyiv_tz = ZoneInfo("Europe/Kiev")
        current_time = datetime.now(kyiv_tz).strftime("%A, %B %d, %Y at %H:%M:%S")
    except Exception:
        import datetime as dt

        utc_now = datetime.utcnow()
        kyiv_time = utc_now + dt.timedelta(hours=3)
        current_time = kyiv_time.strftime("%A, %B %d, %Y at %H:%M:%S")

    # Fetch active DB prompt if available
    active_prompt = None
    try:
        if prompt_manager is not None:
            active_prompt = await prompt_manager.get_active_prompt(chat_id=None)
    except Exception:
        logger.exception("Failed to fetch active prompt from prompt_manager")

    persona_text = None
    persona_source = None
    try:
        if persona_loader is not None:
            # persona_loader.get_system_prompt may accept current_time
            try:
                persona_text = persona_loader.get_system_prompt(
                    current_time=current_time
                )
            except TypeError:
                persona_text = persona_loader.get_system_prompt()
            persona_source = getattr(persona_loader, "persona", None)
    except Exception:
        logger.exception("Failed to get persona text from PersonaLoader")

    if active_prompt:
        effective = active_prompt.prompt_text
        source = f"DB active prompt (version v{active_prompt.version})"
    elif persona_text:
        effective = persona_text
        source = f"Persona template ({getattr(persona_source, 'name', 'template')})"
    else:
        effective = SYSTEM_PERSONA
        source = "Hardcoded app/persona.py (SYSTEM_PERSONA)"

    preview = _format_prompt_preview(effective, max_length=500)

    response = (
        f"📋 <b>Ефективний системний промпт</b>\n\n"
        f"Джерело: {source}\n"
        f"Оновлено/перевірено: {current_time}\n"
        f"Довжина: {len(effective)} символів\n\n"
        f"<b>Попередній перегляд:</b>\n{preview}\n\n"
        f"Повний текст промпту надіслано файлом."
    )

    await message.reply(response)

    prompt_file = BufferedInputFile(
        effective.encode("utf-8"),
        filename=f"effective_system_prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
    )
    await message.reply_document(prompt_file, caption="Ефективний системний промпт")


@router.message(Command(commands=["gryagsetprompt", "setprompt"]))
async def set_prompt_command(
    message: Message,
    settings: Settings,
    prompt_manager: SystemPromptManager,
) -> None:
    """Set custom system prompt.

    Usage:
        /gryagsetprompt <multiline_text> - Set global prompt
        /gryagsetprompt chat <multiline_text> - Set chat-specific prompt

        Or reply to a message containing the prompt text
        Or reply to a document (.txt file) containing the prompt
    """
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    admin_id = message.from_user.id
    prompt_text = None
    scope = "global"
    chat_id_filter = None
    notes = None

    # Check if replying to a document
    if message.reply_to_message and message.reply_to_message.document:
        doc = message.reply_to_message.document
        if doc.mime_type == "text/plain" or doc.file_name.endswith(".txt"):
            # Download document
            file = await message.bot.get_file(doc.file_id)
            file_bytes = io.BytesIO()
            await message.bot.download_file(file.file_path, file_bytes)
            prompt_text = file_bytes.getvalue().decode("utf-8")
            notes = f"Uploaded from file: {doc.file_name}"
        else:
            await message.reply(
                "❌ Будь ласка, надішліть текстовий файл (.txt) з промптом."
            )
            return

    # Check if replying to a text message
    elif message.reply_to_message and message.reply_to_message.text:
        prompt_text = message.reply_to_message.text
        notes = "Set from replied message"

    # Parse command text
    elif message.text:
        parts = message.text.split(maxsplit=2)

        if len(parts) < 2:
            help_text = (
                "📝 <b>Як встановити кастомний промпт:</b>\n\n"
                "1️⃣ Надішліть команду з текстом промпту:\n"
                "<code>/gryagsetprompt\n"
                "Your custom system prompt here...\n"
                "Can be multiple lines.</code>\n\n"
                "2️⃣ Або зробіть reply на повідомлення з промптом:\n"
                "<code>/gryagsetprompt</code> (reply до тексту)\n\n"
                "3️⃣ Або зробіть reply на .txt файл:\n"
                "<code>/gryagsetprompt</code> (reply до файлу)\n\n"
                "4️⃣ Для конкретного чату:\n"
                "<code>/gryagsetprompt chat\n"
                "Chat-specific prompt...</code>\n\n"
                "⚠️ Промпт замінить поточний. Стара версія збережеться в історії."
            )
            await message.reply(help_text)
            return

        # Check if chat-specific
        if parts[1].lower() == "chat":
            scope = "chat"
            chat_id_filter = message.chat.id if message.chat.id < 0 else None

            if chat_id_filter is None:
                await message.reply(
                    "❌ Chat-specific промпти можна встановлювати тільки в групових чатах."
                )
                return

            if len(parts) > 2:
                prompt_text = parts[2]
        else:
            # Global prompt
            prompt_text = " ".join(parts[1:])

    if not prompt_text or len(prompt_text.strip()) < 50:
        await message.reply(
            "❌ Промпт занадто короткий. Мінімум 50 символів. "
            "Системний промпт має бути детальним."
        )
        return

    # Confirmation for very short prompts
    if len(prompt_text) < 200:
        await message.reply(
            f"⚠️ Промпт дуже короткий ({len(prompt_text)} символів). "
            f"Зазвичай системні промпти 500+ символів. Впевнений? Надішли ще раз для підтвердження."
        )
        return

    # Set the prompt
    try:
        new_prompt = await prompt_manager.set_prompt(
            admin_id=admin_id,
            prompt_text=prompt_text,
            chat_id=chat_id_filter,
            scope=scope,
            notes=notes,
        )

        response = (
            f"✅ <b>Системний промпт оновлено!</b>\n\n"
            f"Scope: {new_prompt.scope}\n"
            f"Chat ID: {new_prompt.chat_id or 'Global'}\n"
            f"Версія: v{new_prompt.version}\n"
            f"Довжина: {len(new_prompt.prompt_text)} символів\n\n"
            f"Попередні версії доступні через /gryagprompthistory\n"
            f"Скинути до дефолту: /gryagresetprompt"
        )

        await message.reply(response)

        logger.info(
            f"System prompt updated by admin {admin_id}: "
            f"scope={scope}, chat_id={chat_id_filter}, version={new_prompt.version}"
        )

    except Exception as e:
        logger.error(f"Failed to set system prompt: {e}", exc_info=True)
        await message.reply(f"❌ Помилка при збереженні промпту: {e}")


@router.message(Command(commands=["gryagresetprompt", "resetprompt"]))
async def reset_prompt_command(
    message: Message,
    settings: Settings,
    prompt_manager: SystemPromptManager,
) -> None:
    """Reset to default system prompt.

    Usage:
        /gryagresetprompt - Reset global prompt
        /gryagresetprompt chat - Reset chat-specific prompt
    """
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    admin_id = message.from_user.id
    scope = "global"
    chat_id_filter = None

    # Parse scope
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].lower() == "chat":
            scope = "chat"
            chat_id_filter = message.chat.id if message.chat.id < 0 else None

    try:
        reset = await prompt_manager.reset_to_default(
            admin_id=admin_id, chat_id=chat_id_filter, scope=scope
        )

        if reset:
            response = (
                f"✅ <b>Скинуто до дефолтного промпту</b>\n\n"
                f"Scope: {scope}\n"
                f"Chat ID: {chat_id_filter or 'Global'}\n\n"
                f"Тепер використовується промпт з app/persona.py\n"
                f"Переглянути: /gryagprompt default"
            )
        else:
            response = (
                f"ℹ️ Вже використовується дефолтний промпт для scope={scope}\n"
                f"Нічого не змінено."
            )

        await message.reply(response)

        logger.info(
            f"System prompt reset by admin {admin_id}: "
            f"scope={scope}, chat_id={chat_id_filter}"
        )

    except Exception as e:
        logger.error(f"Failed to reset system prompt: {e}", exc_info=True)
        await message.reply(f"❌ Помилка при скиданні промпту: {e}")


@router.message(Command(commands=["gryagprompthistory", "prompthistory"]))
async def prompt_history_command(
    message: Message,
    settings: Settings,
    prompt_manager: SystemPromptManager,
) -> None:
    """View prompt version history.

    Usage:
        /gryagprompthistory - View global prompt history
        /gryagprompthistory chat - View chat-specific history
    """
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    scope = "global"
    chat_id_filter = None

    # Parse scope
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].lower() == "chat":
            scope = "chat"
            chat_id_filter = message.chat.id if message.chat.id < 0 else None

    try:
        history = await prompt_manager.get_prompt_history(
            chat_id=chat_id_filter, scope=scope, limit=10
        )

        if not history:
            await message.reply(
                f"📋 Історія промптів порожня для scope={scope}\n"
                f"Ще не було кастомних промптів."
            )
            return

        response = f"📜 <b>Історія системних промптів</b>\n\n"
        response += f"Scope: {scope}\n"
        response += f"Chat ID: {chat_id_filter or 'Global'}\n"
        response += f"Всього версій: {len(history)}\n\n"

        for prompt in history:
            status = "🟢 Активна" if prompt.is_active else "⚪️ Неактивна"
            response += (
                f"<b>Версія {prompt.version}</b> {status}\n"
                f"  Створено: {_format_timestamp(prompt.created_at)}\n"
                f"  Адмін ID: {prompt.admin_id}\n"
                f"  Довжина: {len(prompt.prompt_text)} символів\n"
            )
            if prompt.notes:
                response += f"  Нотатки: {prompt.notes}\n"
            response += f"  Попередній перегляд: {_format_prompt_preview(prompt.prompt_text, 100)}\n\n"

        response += (
            f"💡 Щоб активувати стару версію:\n"
            f"<code>/gryagactivateprompt VERSION</code>"
        )

        await message.reply(response)

    except Exception as e:
        logger.error(f"Failed to get prompt history: {e}", exc_info=True)
        await message.reply(f"❌ Помилка при отриманні історії: {e}")


@router.message(Command(commands=["gryagactivateprompt", "activateprompt"]))
async def activate_prompt_version_command(
    message: Message,
    settings: Settings,
    prompt_manager: SystemPromptManager,
) -> None:
    """Activate a specific version from history (rollback).

    Usage:
        /gryagactivateprompt <version> - Activate global prompt version
        /gryagactivateprompt chat <version> - Activate chat-specific version
    """
    if not message.from_user or not _is_admin(message.from_user.id, settings):
        await message.reply(ADMIN_ONLY)
        return

    admin_id = message.from_user.id
    scope = "global"
    chat_id_filter = None
    version = None

    # Parse command
    if not message.text:
        await message.reply("❌ Використання: /gryagactivateprompt <version>")
        return

    parts = message.text.split()

    if len(parts) < 2:
        await message.reply(
            "❌ Вкажіть версію для активації.\n"
            "Приклад: <code>/gryagactivateprompt 3</code>\n"
            "Подивитись версії: /gryagprompthistory"
        )
        return

    # Check for chat scope
    if parts[1].lower() == "chat":
        scope = "chat"
        chat_id_filter = message.chat.id if message.chat.id < 0 else None

        if len(parts) < 3:
            await message.reply("❌ Вкажіть версію після 'chat'")
            return

        try:
            version = int(parts[2])
        except ValueError:
            await message.reply("❌ Версія має бути числом")
            return
    else:
        try:
            version = int(parts[1])
        except ValueError:
            await message.reply("❌ Версія має бути числом")
            return

    try:
        activated = await prompt_manager.activate_version(
            admin_id=admin_id,
            version=version,
            chat_id=chat_id_filter,
            scope=scope,
        )

        if activated:
            response = (
                f"✅ <b>Активовано версію {version}</b>\n\n"
                f"Scope: {scope}\n"
                f"Chat ID: {chat_id_filter or 'Global'}\n"
                f"Створено: {_format_timestamp(activated.created_at)}\n"
                f"Довжина: {len(activated.prompt_text)} символів\n\n"
                f"Переглянути: /gryagprompt"
            )
        else:
            response = (
                f"❌ Версію {version} не знайдено для scope={scope}\n"
                f"Перевірте доступні версії: /gryagprompthistory"
            )

        await message.reply(response)

        if activated:
            logger.info(
                f"Activated prompt version {version} by admin {admin_id}: "
                f"scope={scope}, chat_id={chat_id_filter}"
            )

    except Exception as e:
        logger.error(f"Failed to activate prompt version: {e}", exc_info=True)
        await message.reply(f"❌ Помилка при активації версії: {e}")
