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
    gemini_embed_model: str = Field(
        "models/text-embedding-004", alias="GEMINI_EMBED_MODEL"
    )
    db_path: Path = Field(Path("./gryag.db"), alias="DB_PATH")
    max_turns: int = Field(50, alias="MAX_TURNS", ge=1)
    context_summary_threshold: int = Field(30, alias="CONTEXT_SUMMARY_THRESHOLD", ge=5)
    per_user_per_hour: int = Field(5, alias="PER_USER_PER_HOUR", ge=1)
    use_redis: bool = Field(False, alias="USE_REDIS")
    redis_url: str | None = Field("redis://localhost:6379/0", alias="REDIS_URL")
    admin_user_ids: list[int] = Field(default_factory=list, alias="ADMIN_USER_IDS")
    retention_days: int = Field(30, alias="RETENTION_DAYS", ge=1)
    enable_search_grounding: bool = Field(False, alias="ENABLE_SEARCH_GROUNDING")

    # Weather API configuration
    openweather_api_key: str | None = Field(None, alias="OPENWEATHER_API_KEY")
    openweather_base_url: str = Field(
        "https://api.openweathermap.org/data/2.5", alias="OPENWEATHER_BASE_URL"
    )

    # Currency API configuration
    exchange_rate_api_key: str | None = Field(None, alias="EXCHANGE_RATE_API_KEY")
    exchange_rate_base_url: str = Field(
        "https://v6.exchangerate-api.com", alias="EXCHANGE_RATE_BASE_URL"
    )

    # User profiling configuration
    enable_user_profiling: bool = Field(True, alias="ENABLE_USER_PROFILING")
    user_profile_retention_days: int = Field(
        365, alias="USER_PROFILE_RETENTION_DAYS", ge=1
    )
    max_facts_per_user: int = Field(100, alias="MAX_FACTS_PER_USER", ge=1)
    fact_confidence_threshold: float = Field(
        0.7, alias="FACT_CONFIDENCE_THRESHOLD", ge=0.0, le=1.0
    )
    fact_extraction_enabled: bool = Field(True, alias="FACT_EXTRACTION_ENABLED")
    profile_summarization_interval_hours: int = Field(
        24, alias="PROFILE_SUMMARIZATION_INTERVAL_HOURS", ge=1
    )
    min_messages_for_extraction: int = Field(
        5, alias="MIN_MESSAGES_FOR_EXTRACTION", ge=1
    )

    # Profile summarization configuration (optimized for i5-6500)
    enable_profile_summarization: bool = Field(
        False, alias="ENABLE_PROFILE_SUMMARIZATION"
    )
    profile_summarization_hour: int = Field(
        3, alias="PROFILE_SUMMARIZATION_HOUR", ge=0, le=23
    )  # Run at 3 AM to avoid peak usage
    profile_summarization_batch_size: int = Field(
        30, alias="PROFILE_SUMMARIZATION_BATCH_SIZE", ge=10, le=100
    )  # Conservative for i5-6500
    max_profiles_per_day: int = Field(
        50, alias="MAX_PROFILES_PER_DAY", ge=1
    )  # Limit to avoid overload

    # Fact extraction method configuration
    fact_extraction_method: str = Field(
        "hybrid", alias="FACT_EXTRACTION_METHOD"
    )  # rule_based, local_model, hybrid, gemini
    local_model_path: str | None = Field(None, alias="LOCAL_MODEL_PATH")
    local_model_threads: int | None = Field(None, alias="LOCAL_MODEL_THREADS")
    enable_gemini_fallback: bool = Field(False, alias="ENABLE_GEMINI_FALLBACK")

    # Continuous monitoring configuration (Phase 1+)
    enable_continuous_monitoring: bool = Field(
        True, alias="ENABLE_CONTINUOUS_MONITORING"
    )
    enable_message_filtering: bool = Field(
        False, alias="ENABLE_MESSAGE_FILTERING"
    )  # Phase 1: False, Phase 3: True
    enable_async_processing: bool = Field(
        False, alias="ENABLE_ASYNC_PROCESSING"
    )  # Phase 1: False, Phase 3: True

    # Conversation window settings
    conversation_window_size: int = Field(
        8, alias="CONVERSATION_WINDOW_SIZE", ge=3, le=20
    )  # Number of messages per window
    conversation_window_timeout: int = Field(
        180, alias="CONVERSATION_WINDOW_TIMEOUT", ge=60, le=600
    )  # Seconds before window closes
    max_concurrent_windows: int = Field(
        100, alias="MAX_CONCURRENT_WINDOWS", ge=10, le=500
    )

    # Event queue settings
    monitoring_workers: int = Field(
        3, alias="MONITORING_WORKERS", ge=1, le=10
    )  # Number of async workers
    max_queue_size: int = Field(1000, alias="MAX_QUEUE_SIZE", ge=100, le=10000)
    enable_circuit_breaker: bool = Field(True, alias="ENABLE_CIRCUIT_BREAKER")
    circuit_breaker_threshold: int = Field(
        5, alias="CIRCUIT_BREAKER_THRESHOLD", ge=3, le=20
    )  # Failures before opening
    circuit_breaker_timeout: int = Field(
        60, alias="CIRCUIT_BREAKER_TIMEOUT", ge=30, le=300
    )  # Seconds before retry

    # Proactive response settings (Phase 4)
    enable_proactive_responses: bool = Field(
        False, alias="ENABLE_PROACTIVE_RESPONSES"
    )  # Phase 1-3: False, Phase 4: True
    proactive_confidence_threshold: float = Field(
        0.75, alias="PROACTIVE_CONFIDENCE_THRESHOLD", ge=0.5, le=1.0
    )
    proactive_cooldown_seconds: int = Field(
        300, alias="PROACTIVE_COOLDOWN_SECONDS", ge=60, le=1800
    )  # Minimum time between proactive responses

    # System health monitoring
    enable_health_metrics: bool = Field(True, alias="ENABLE_HEALTH_METRICS")
    health_check_interval: int = Field(
        300, alias="HEALTH_CHECK_INTERVAL", ge=60, le=3600
    )  # Seconds between health checks

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
