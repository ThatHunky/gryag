from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_token: str = Field(..., alias="TELEGRAM_TOKEN")
    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.5-flash", alias="GEMINI_MODEL")
    gemini_embed_model: str = Field("models/text-embedding-004", alias="GEMINI_EMBED_MODEL")
    db_path: Path = Field(Path("./gryag.db"), alias="DB_PATH")
    max_turns: int = Field(50, alias="MAX_TURNS", ge=1)
    per_user_per_hour: int = Field(5, alias="PER_USER_PER_HOUR", ge=1)
    use_redis: bool = Field(False, alias="USE_REDIS")
    redis_url: str | None = Field("redis://localhost:6379/0", alias="REDIS_URL")
    admin_user_ids: list[int] = Field(default_factory=list, alias="ADMIN_USER_IDS")
    retention_days: int = Field(30, alias="RETENTION_DAYS", ge=1)
    enable_search_grounding: bool = Field(False, alias="ENABLE_SEARCH_GROUNDING")

    @property
    def db_path_str(self) -> str:
        return str(self.db_path)

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_admins(cls, value: object) -> list[int]:
        if value in (None, ""):
            return []
        if isinstance(value, str):
            parts = [part.strip() for part in value.split(",")]
            return [int(part) for part in parts if part]
        if isinstance(value, (list, tuple, set)):
            return [int(item) for item in value]
        if isinstance(value, int):
            return [value]
        raise ValueError("Invalid ADMIN_USER_IDS value")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
