import asyncio
import logging
import os
from typing import TYPE_CHECKING
from gemini_client import GeminiClient

# Use typing-only imports when available to keep static type checkers happy.
if TYPE_CHECKING:
	from dotenv import load_dotenv  # type: ignore
	from aiogram import Bot, Dispatcher  # type: ignore
	from aiogram.types import Message  # type: ignore
else:
	# runtime imports with graceful fallbacks so the file parses in editors
	try:
		from dotenv import load_dotenv
	except Exception:
		def load_dotenv():
			return None

	try:
		from aiogram import Bot, Dispatcher
		from aiogram.types import Message
	except Exception:
		# Minimal runtime stubs so the module can be opened/edited without installed deps.
		class _Me:
			def __init__(self):
				self.username = "gryag_bot"
				self.id = 0

		class Bot:
			def __init__(self, *args, **kwargs):
				pass

			async def get_me(self):
				return _Me()

			@property
			def session(self):
				class _S:
					async def close(self):
						return None

				return _S()

		class Dispatcher:
			def __init__(self):
				pass

			def message(self):
				def decorator(f):
					return f

				return decorator

			async def start_polling(self, bot):
				# no-op in stub
				return None

		class Message:
			def __init__(self):
				self.text = None
				self.caption = None
				self.entities = None
				self.chat = type("_C", (), {"id": 0})()
				self.from_user = type("_U", (), {"full_name": ""})()

			async def reply(self, *args, **kwargs):
				return None

	# call load_dotenv at runtime to populate env vars if python-dotenv is installed
	try:
		load_dotenv()
	except Exception:
		import asyncio
		import logging
		import os
		from typing import Optional, TYPE_CHECKING

		# Use typing-only imports when available to keep static type checkers happy.
		if TYPE_CHECKING:
			from dotenv import load_dotenv  # type: ignore
			from aiogram import Bot, Dispatcher  # type: ignore
			from aiogram.types import Message  # type: ignore
		else:
			# runtime imports with graceful fallbacks so the file parses in editors
			try:
				from dotenv import load_dotenv
			except Exception:
				def load_dotenv():
					return None

			try:
				from aiogram import Bot, Dispatcher
				from aiogram.types import Message
			except Exception:
				# Minimal runtime stubs so the module can be opened/edited without installed deps.
				class _Me:
					def __init__(self):
						self.username = "gryag_bot"
						self.id = 0

				class Bot:
					def __init__(self, *args, **kwargs):
						pass

					async def get_me(self):
						return _Me()

					@property
					def session(self):
						class _S:
							async def close(self):
								return None

						return _S()

				class Dispatcher:
					def __init__(self):
						pass

					def message(self):
						def decorator(f):
							return f

						return decorator

					async def start_polling(self, bot):
						# no-op in stub
						return None

				class Message:
					def __init__(self):
						self.text = None
						self.caption = None
						self.entities = None
						self.chat = type("_C", (), {"id": 0})()
						self.from_user = type("_U", (), {"full_name": ""})()

					async def reply(self, *args, **kwargs):
						return None

			# call load_dotenv at runtime to populate env vars if python-dotenv is installed
			try:
				load_dotenv()
			except Exception:
				# noop if load_dotenv not available
				pass

		# Configuration comes from .env
		BOT_TOKEN = os.getenv("BOT_TOKEN")
		ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
		TARGET_GROUP_ID = int(os.getenv("TARGET_GROUP_ID", "0"))

		logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
		logger = logging.getLogger(__name__)

		if not BOT_TOKEN:
			logger.error("BOT_TOKEN is not set in .env. Please set it before running the bot.")
			raise SystemExit("BOT_TOKEN not set in .env")

		bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else Bot()
		dp = Dispatcher()


		async def _get_bot_username() -> str:
			"""Get bot username (cached per-call)."""
			me = await bot.get_me()
			return (me.username or "gryag_bot")


		def _text_from_message(message) -> str:
			return (getattr(message, "text", None) or getattr(message, "caption", None) or "") or ""


		async def handle_mentions(message):
			"""Reply when the bot is mentioned by name or username inside the target group.

			Rules:
			- Only act if message.chat.id equals TARGET_GROUP_ID (if TARGET_GROUP_ID is non-zero).
			- Match the Ukrainian name "гряг" (case-insensitive) or the bot username like "@gryag_bot".
			"""
			try:
				# Respect configured target group if provided
				if TARGET_GROUP_ID and getattr(message, "chat", type("_", (), {"id": None})()).id != TARGET_GROUP_ID:
					return

				text = _text_from_message(message)
				lowered = text.lower()

				# check for plain name
				if "гряг" in lowered:
					await message.reply(f"Я тут, {getattr(message, 'from_user', type('U', (), {'full_name': ''})()).full_name}!")
					return

				# check for username mention (safer to fetch actual bot username)
				bot_username = (await _get_bot_username()).lower()
				if f"@{bot_username}" in lowered:
					await message.reply(f"Я тут, {getattr(message, 'from_user', type('U', (), {'full_name': ''})()).full_name}!")
					return

				# Also inspect entities for explicit mentions (text_mention / mention)
				entities = getattr(message, "entities", None)
				if entities:
					for ent in entities:
						ent_type = getattr(ent, "type", None)
						if ent_type == "text_mention":
							# text_mention has a user attached
							if getattr(ent, "user", None) and getattr(ent.user, "id", None) == (await bot.get_me()).id:
								await message.reply(f"Я тут, {getattr(message, 'from_user', type('U', (), {'full_name': ''})()).full_name}!")
								return
						if ent_type == "mention":
							# extract text slice safely
							start = getattr(ent, "offset", 0)
							length = getattr(ent, "length", 0)
							end = start + length
							mention_text = text[start:end].lower()
							if mention_text == f"@{bot_username}":
								await message.reply(f"Я тут, {getattr(message, 'from_user', type('U', (), {'full_name': ''})()).full_name}!")
								return
			except Exception:
				logger.exception("Error while handling message")


		async def handle_askgem(message):
			"""Simple command handler to call Gemini API: `/askgem your prompt`"""
			text = _text_from_message(message).strip()
			if not text:
				await message.reply("Вкажіть запит після команди, наприклад: /askgem Привіт")
				return

			# strip command if it appears
			if text.startswith("/askgem"):
				prompt = text[len("/askgem"):].strip()
			else:
				prompt = text

			try:
				client = GeminiClient()
				answer = await client.generate_text(prompt)
				await message.reply(answer)
			except Exception as e:
				logger.exception("Gemini request failed")
				await message.reply(f"Помилка при зверненні до Gemini: {e}")


		# Register handlers for aiogram when available (stub Dispatcher is no-op)
		try:
			# aiogram v3 style
			dp.message.register(handle_mentions)
			dp.message.register(handle_askgem, commands=["askgem"])
		except Exception:
			# dp.message may be a decorator in stub — try alternate registration
			try:
				# If dp.message is decorator-like
				dp.message()(handle_mentions)
				dp.message()(handle_askgem)
			except Exception:
				# give up silently — the runtime aiogram will allow registering differently
				pass


		async def on_startup() -> None:
			me = await bot.get_me()
			logger.info("Bot started as @%s (id=%s)", me.username, me.id)
			logger.info("Configured target group id=%s admin id=%s", TARGET_GROUP_ID, ADMIN_ID)


		async def main() -> None:
			await on_startup()
			try:
				await dp.start_polling(bot)
			finally:
				await bot.session.close()


		if __name__ == "__main__":
			asyncio.run(main())
