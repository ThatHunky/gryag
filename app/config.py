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
    max_turns: int = Field(
        20, alias="MAX_TURNS", ge=1
    )  # Reduced from 50 to prevent token overflow
    per_user_per_hour: int = Field(5, alias="PER_USER_PER_HOUR", ge=1)
    context_summary_threshold: int = Field(30, alias="CONTEXT_SUMMARY_THRESHOLD", ge=5)
    use_redis: bool = Field(False, alias="USE_REDIS")
    redis_url: str | None = Field("redis://localhost:6379/0", alias="REDIS_URL")
    admin_user_ids: str = Field("", alias="ADMIN_USER_IDS")
    retention_days: int = Field(7, alias="RETENTION_DAYS", ge=1)
    # Pruning configuration
    retention_enabled: bool = Field(True, alias="RETENTION_ENABLED")
    retention_prune_interval_seconds: int = Field(
        86400, alias="RETENTION_PRUNE_INTERVAL_SECONDS", ge=60
    )  # Default: run once per day
    enable_search_grounding: bool = Field(False, alias="ENABLE_SEARCH_GROUNDING")

    # Media handling configuration
    gemini_max_media_items: int = Field(
        28, alias="GEMINI_MAX_MEDIA_ITEMS", ge=1, le=100
    )  # Conservative limit for Gemma (max 32), other models may support more

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

    # Image generation configuration
    enable_image_generation: bool = Field(False, alias="ENABLE_IMAGE_GENERATION")
    image_generation_api_key: str | None = Field(
        None, alias="IMAGE_GENERATION_API_KEY"
    )  # Optional separate API key for image generation (defaults to gemini_api_key)
    image_generation_daily_limit: int = Field(
        1, alias="IMAGE_GENERATION_DAILY_LIMIT", ge=1, le=10
    )  # Images per user per day (admins unlimited)

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

    # Fact extraction configuration - uses Google Gemini API (rule-based + optional Gemini fallback)
    enable_gemini_fact_extraction: bool = Field(
        True, alias="ENABLE_GEMINI_FACT_EXTRACTION"
    )

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

    # ═══════════════════════════════════════════════════════════════════════════
    # Memory and Context Improvements (Phase 1+)
    # ═══════════════════════════════════════════════════════════════════════════

    # Multi-Level Context
    enable_multi_level_context: bool = Field(True, alias="ENABLE_MULTI_LEVEL_CONTEXT")
    immediate_context_size: int = Field(5, alias="IMMEDIATE_CONTEXT_SIZE", ge=1, le=20)
    recent_context_size: int = Field(30, alias="RECENT_CONTEXT_SIZE", ge=5, le=100)
    relevant_context_size: int = Field(10, alias="RELEVANT_CONTEXT_SIZE", ge=1, le=50)
    context_token_budget: int = Field(
        8000, alias="CONTEXT_TOKEN_BUDGET", ge=1000, le=30000
    )

    # Hybrid Search
    enable_hybrid_search: bool = Field(True, alias="ENABLE_HYBRID_SEARCH")
    enable_keyword_search: bool = Field(True, alias="ENABLE_KEYWORD_SEARCH")
    enable_temporal_boosting: bool = Field(True, alias="ENABLE_TEMPORAL_BOOSTING")
    temporal_half_life_days: int = Field(
        7, alias="TEMPORAL_HALF_LIFE_DAYS", ge=1, le=90
    )
    max_search_candidates: int = Field(
        500, alias="MAX_SEARCH_CANDIDATES", ge=50, le=2000
    )
    semantic_weight: float = Field(
        0.5, alias="SEMANTIC_WEIGHT", ge=0.0, le=1.0
    )  # Weight for semantic similarity in hybrid search
    keyword_weight: float = Field(
        0.3, alias="KEYWORD_WEIGHT", ge=0.0, le=1.0
    )  # Weight for keyword matching
    temporal_weight: float = Field(
        0.2, alias="TEMPORAL_WEIGHT", ge=0.0, le=1.0
    )  # Weight for recency

    # Episodic Memory
    enable_episodic_memory: bool = Field(True, alias="ENABLE_EPISODIC_MEMORY")
    episode_min_importance: float = Field(
        0.6, alias="EPISODE_MIN_IMPORTANCE", ge=0.0, le=1.0
    )
    episode_min_messages: int = Field(5, alias="EPISODE_MIN_MESSAGES", ge=3, le=50)
    auto_create_episodes: bool = Field(True, alias="AUTO_CREATE_EPISODES")
    episode_detection_interval: int = Field(
        300, alias="EPISODE_DETECTION_INTERVAL", ge=60, le=3600
    )  # Seconds

    # Episode Boundary Detection (Phase 4.1)
    episode_boundary_threshold: float = Field(
        0.6, alias="EPISODE_BOUNDARY_THRESHOLD", ge=0.0, le=1.0
    )  # Combined score threshold for creating boundary
    episode_short_gap_seconds: int = Field(
        120, alias="EPISODE_SHORT_GAP_SECONDS", ge=30, le=600
    )  # 2 minutes
    episode_medium_gap_seconds: int = Field(
        900, alias="EPISODE_MEDIUM_GAP_SECONDS", ge=300, le=3600
    )  # 15 minutes
    episode_long_gap_seconds: int = Field(
        3600, alias="EPISODE_LONG_GAP_SECONDS", ge=600, le=86400
    )  # 1 hour
    episode_low_similarity_threshold: float = Field(
        0.3, alias="EPISODE_LOW_SIMILARITY_THRESHOLD", ge=0.0, le=1.0
    )
    episode_medium_similarity_threshold: float = Field(
        0.5, alias="EPISODE_MEDIUM_SIMILARITY_THRESHOLD", ge=0.0, le=1.0
    )
    episode_high_similarity_threshold: float = Field(
        0.7, alias="EPISODE_HIGH_SIMILARITY_THRESHOLD", ge=0.0, le=1.0
    )

    # Episode Monitoring (Phase 4.2)
    episode_window_timeout: int = Field(
        1800, alias="EPISODE_WINDOW_TIMEOUT", ge=300, le=7200
    )  # Seconds before window closes (30 minutes)
    episode_window_max_messages: int = Field(
        50, alias="EPISODE_WINDOW_MAX_MESSAGES", ge=10, le=200
    )  # Max messages per window
    episode_monitor_interval: int = Field(
        300, alias="EPISODE_MONITOR_INTERVAL", ge=60, le=3600
    )  # Background check interval (5 minutes)

    # Fact Graphs
    enable_fact_graphs: bool = Field(True, alias="ENABLE_FACT_GRAPHS")
    auto_infer_relationships: bool = Field(True, alias="AUTO_INFER_RELATIONSHIPS")
    max_graph_hops: int = Field(2, alias="MAX_GRAPH_HOPS", ge=1, le=5)
    semantic_similarity_threshold: float = Field(
        0.7, alias="SEMANTIC_SIMILARITY_THRESHOLD", ge=0.0, le=1.0
    )
    fact_relationship_min_weight: float = Field(
        0.3, alias="FACT_RELATIONSHIP_MIN_WEIGHT", ge=0.0, le=1.0
    )

    # Temporal Awareness
    enable_fact_versioning: bool = Field(True, alias="ENABLE_FACT_VERSIONING")
    track_fact_changes: bool = Field(True, alias="TRACK_FACT_CHANGES")
    recency_weight: float = Field(
        0.3, alias="RECENCY_WEIGHT", ge=0.0, le=1.0
    )  # Overall recency importance

    # Adaptive Memory
    enable_adaptive_retention: bool = Field(True, alias="ENABLE_ADAPTIVE_RETENTION")
    enable_memory_consolidation: bool = Field(True, alias="ENABLE_MEMORY_CONSOLIDATION")
    consolidation_interval_hours: int = Field(
        24, alias="CONSOLIDATION_INTERVAL_HOURS", ge=1, le=168
    )
    min_retention_days: int = Field(30, alias="MIN_RETENTION_DAYS", ge=7, le=90)
    max_retention_days: int = Field(365, alias="MAX_RETENTION_DAYS", ge=30, le=3650)
    base_retention_days: int = Field(
        90, alias="BASE_RETENTION_DAYS", ge=30, le=365
    )  # Base for adaptive calculation

    # Token Optimization (Phase 5.2)
    enable_token_tracking: bool = Field(True, alias="ENABLE_TOKEN_TRACKING")
    enable_embedding_quantization: bool = Field(
        False, alias="ENABLE_EMBEDDING_QUANTIZATION"
    )  # 8-bit quantization to reduce storage
    enable_response_compression: bool = Field(
        True, alias="ENABLE_RESPONSE_COMPRESSION"
    )  # Compress long responses before storage
    enable_semantic_deduplication: bool = Field(
        True, alias="ENABLE_SEMANTIC_DEDUPLICATION"
    )  # Collapse similar search results
    deduplication_similarity_threshold: float = Field(
        0.85, alias="DEDUPLICATION_SIMILARITY_THRESHOLD", ge=0.7, le=0.99
    )  # Threshold for considering snippets duplicates
    max_tool_response_tokens: int = Field(
        300, alias="MAX_TOOL_RESPONSE_TOKENS", ge=100, le=1000
    )  # Maximum tokens per tool response

    # Compact Conversation Format (Phase 6 - October 2025)
    enable_compact_conversation_format: bool = Field(
        False, alias="ENABLE_COMPACT_CONVERSATION_FORMAT"
    )  # Use plain text format instead of JSON (70-80% token savings)
    compact_format_max_history: int = Field(
        50, alias="COMPACT_FORMAT_MAX_HISTORY", ge=10, le=100
    )  # More messages due to efficiency

    # Performance & Caching
    enable_result_caching: bool = Field(True, alias="ENABLE_RESULT_CACHING")
    cache_ttl_seconds: int = Field(3600, alias="CACHE_TTL_SECONDS", ge=60, le=86400)
    max_cache_size_mb: int = Field(100, alias="MAX_CACHE_SIZE_MB", ge=10, le=1000)
    enable_embedding_cache: bool = Field(True, alias="ENABLE_EMBEDDING_CACHE")

    # ═══════════════════════════════════════════════════════════════════════════
    # Bot Self-Learning (Phase 5)
    # ═══════════════════════════════════════════════════════════════════════════

    # Bot Self-Learning
    enable_bot_self_learning: bool = Field(True, alias="ENABLE_BOT_SELF_LEARNING")
    bot_learning_confidence_threshold: float = Field(
        0.5, alias="BOT_LEARNING_CONFIDENCE_THRESHOLD", ge=0.0, le=1.0
    )
    bot_learning_min_evidence: int = Field(
        3, alias="BOT_LEARNING_MIN_EVIDENCE", ge=1, le=20
    )
    enable_bot_persona_adaptation: bool = Field(
        True, alias="ENABLE_BOT_PERSONA_ADAPTATION"
    )
    enable_temporal_decay: bool = Field(
        True, alias="ENABLE_TEMPORAL_DECAY"
    )  # Outdated facts lose confidence
    enable_semantic_dedup: bool = Field(
        True, alias="ENABLE_SEMANTIC_DEDUP"
    )  # Use embeddings for fact dedup
    enable_gemini_insights: bool = Field(
        True, alias="ENABLE_GEMINI_INSIGHTS"
    )  # Self-reflection via Gemini
    bot_insight_interval_hours: int = Field(
        168, alias="BOT_INSIGHT_INTERVAL_HOURS", ge=24, le=720
    )  # Weekly by default
    bot_reaction_timeout_seconds: int = Field(
        300, alias="BOT_REACTION_TIMEOUT_SECONDS", ge=30, le=3600
    )  # Wait time for user reaction

    # Memory tool calling configuration (Phase 5.1)
    enable_tool_based_memory: bool = Field(True, alias="ENABLE_TOOL_BASED_MEMORY")
    memory_tool_async: bool = Field(
        True, alias="MEMORY_TOOL_ASYNC"
    )  # Run memory ops in background
    memory_tool_timeout_ms: int = Field(
        200, alias="MEMORY_TOOL_TIMEOUT_MS", ge=50, le=1000
    )
    memory_tool_queue_size: int = Field(
        1000, alias="MEMORY_TOOL_QUEUE_SIZE", ge=100, le=10000
    )
    enable_automated_memory_fallback: bool = Field(
        True, alias="ENABLE_AUTOMATED_MEMORY_FALLBACK"
    )

    # ═══════════════════════════════════════════════════════════════════════════════
    # Chat Public Memory (October 2025)
    # Group-level memory for chat-wide facts, preferences, and culture
    # ═══════════════════════════════════════════════════════════════════════════════

    # Master switch
    enable_chat_memory: bool = Field(True, alias="ENABLE_CHAT_MEMORY")

    # Extraction
    enable_chat_fact_extraction: bool = Field(True, alias="ENABLE_CHAT_FACT_EXTRACTION")
    chat_fact_min_confidence: float = Field(
        0.6, alias="CHAT_FACT_MIN_CONFIDENCE", ge=0.0, le=1.0
    )
    chat_fact_extraction_method: str = Field(
        "hybrid", alias="CHAT_FACT_EXTRACTION_METHOD"
    )  # pattern, statistical, llm, hybrid

    # Retrieval
    chat_facts_in_context: bool = Field(True, alias="CHAT_FACTS_IN_CONTEXT")
    max_chat_facts_in_context: int = Field(
        8, alias="MAX_CHAT_FACTS_IN_CONTEXT", ge=1, le=20
    )
    chat_context_token_budget: int = Field(
        480, alias="CHAT_CONTEXT_TOKEN_BUDGET", ge=100, le=2000
    )  # 40% of background budget

    # Quality
    enable_chat_fact_deduplication: bool = Field(
        True, alias="ENABLE_CHAT_FACT_DEDUPLICATION"
    )
    chat_fact_similarity_threshold: float = Field(
        0.85, alias="CHAT_FACT_SIMILARITY_THRESHOLD", ge=0.0, le=1.0
    )
    chat_fact_temporal_half_life_days: int = Field(
        30, alias="CHAT_FACT_TEMPORAL_HALF_LIFE_DAYS", ge=1, le=365
    )

    # ═══════════════════════════════════════════════════════════════════════════════
    # Universal Bot Configuration (Phase 1)
    # Bot Identity, Personality, and Chat Management
    # ═══════════════════════════════════════════════════════════════════════════════

    # Bot Identity
    bot_name: str = Field("gryag", alias="BOT_NAME")  # Display name for responses
    bot_username: str | None = Field(
        None, alias="BOT_USERNAME"
    )  # Telegram username (without @), auto-detected if None
    bot_trigger_patterns: str = Field(
        "", alias="BOT_TRIGGER_PATTERNS"
    )  # Comma-separated trigger words, empty = use persona config
    command_prefix: str = Field(
        "gryag", alias="COMMAND_PREFIX"
    )  # Prefix for admin commands (/gryagban, etc.)

    # Personality Configuration
    persona_config: str = Field(
        "", alias="PERSONA_CONFIG"
    )  # Path to persona YAML file, empty = use hardcoded persona
    response_templates: str = Field(
        "", alias="RESPONSE_TEMPLATES"
    )  # Path to response templates JSON, empty = use hardcoded responses
    bot_language: str = Field("uk", alias="BOT_LANGUAGE")  # Primary language code
    enable_profanity: bool = Field(
        True, alias="ENABLE_PROFANITY"
    )  # Allow strong language in responses

    # Chat Management
    bot_behavior_mode: str = Field(
        "global", alias="BOT_BEHAVIOR_MODE"
    )  # global, whitelist, blacklist
    allowed_chat_ids: str = Field(
        "", alias="ALLOWED_CHAT_IDS"
    )  # Comma-separated chat IDs for whitelist mode
    blocked_chat_ids: str = Field(
        "", alias="BLOCKED_CHAT_IDS"
    )  # Comma-separated chat IDs for blacklist mode
    admin_chat_ids: str = Field(
        "", alias="ADMIN_CHAT_IDS"
    )  # Comma-separated chat IDs where admin commands work, empty = all chats
    ignore_private_chats: bool = Field(
        False, alias="IGNORE_PRIVATE_CHATS"
    )  # Only operate in groups

    # Feature Toggles
    enable_chat_filtering: bool = Field(
        False, alias="ENABLE_CHAT_FILTERING"
    )  # Enable chat restrictions
    enable_custom_commands: bool = Field(
        False, alias="ENABLE_CUSTOM_COMMANDS"
    )  # Use configurable command names
    enable_persona_templates: bool = Field(
        True, alias="ENABLE_PERSONA_TEMPLATES"
    )  # Use template-based responses (default enabled for universality)

    # ═══════════════════════════════════════════════════════════════════════════
    # Logging Configuration
    # ═══════════════════════════════════════════════════════════════════════════

    log_dir: Path = Field(Path("./logs"), alias="LOG_DIR")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_format: str = Field("text", alias="LOG_FORMAT")  # text or json
    log_retention_days: int = Field(7, alias="LOG_RETENTION_DAYS", ge=1, le=90)
    log_max_bytes: int = Field(
        10 * 1024 * 1024,  # 10 MB
        alias="LOG_MAX_BYTES",
        ge=1024 * 1024,
        le=100 * 1024 * 1024,
    )
    log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT", ge=1, le=30)
    enable_console_logging: bool = Field(True, alias="ENABLE_CONSOLE_LOGGING")
    enable_file_logging: bool = Field(True, alias="ENABLE_FILE_LOGGING")

    @property
    def db_path_str(self) -> str:
        return str(self.db_path)

    @property
    def admin_user_ids_list(self) -> list[int]:
        """Parse admin user IDs from string to list."""
        if not self.admin_user_ids:
            return []
        parts = [part.strip() for part in self.admin_user_ids.split(",")]
        return [int(part) for part in parts if part]

    @property
    def allowed_chat_ids_list(self) -> list[int]:
        """Parse allowed chat IDs from string to list."""
        if not self.allowed_chat_ids:
            return []
        parts = [part.strip() for part in self.allowed_chat_ids.split(",")]
        return [int(part) for part in parts if part]

    @property
    def blocked_chat_ids_list(self) -> list[int]:
        """Parse blocked chat IDs from string to list."""
        if not self.blocked_chat_ids:
            return []
        parts = [part.strip() for part in self.blocked_chat_ids.split(",")]
        return [int(part) for part in parts if part]

    @property
    def admin_chat_ids_list(self) -> list[int]:
        """Parse admin chat IDs from string to list."""
        if not self.admin_chat_ids:
            return []
        parts = [part.strip() for part in self.admin_chat_ids.split(",")]
        return [int(part) for part in parts if part]

    @property
    def bot_trigger_patterns_list(self) -> list[str]:
        """Parse bot trigger patterns from string to list."""
        if not self.bot_trigger_patterns:
            return []
        return [
            part.strip()
            for part in self.bot_trigger_patterns.split(",")
            if part.strip()
        ]

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_admins(cls, value: object) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple, set)):
            return ",".join(str(item) for item in value)
        if isinstance(value, int):
            return str(value)
        raise ValueError("Invalid ADMIN_USER_IDS value")

    @field_validator("bot_behavior_mode")
    @classmethod
    def _validate_behavior_mode(cls, v: str) -> str:
        """Validate bot behavior mode is a valid option."""
        valid_modes = {"global", "whitelist", "blacklist"}
        if v not in valid_modes:
            raise ValueError(
                f"bot_behavior_mode must be one of {valid_modes}, got '{v}'"
            )
        return v

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got '{v}'")
        return v_upper

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, v: str) -> str:
        """Validate log format is valid."""
        valid_formats = {"text", "json"}
        if v not in valid_formats:
            raise ValueError(f"log_format must be one of {valid_formats}, got '{v}'")
        return v

    @field_validator("semantic_weight", "keyword_weight", "temporal_weight")
    @classmethod
    def _validate_search_weights(cls, v: float, info) -> float:
        """Validate that search weights are reasonable and will be checked for sum."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"{info.field_name} must be between 0.0 and 1.0, got {v}")
        return v

    def model_post_init(self, __context) -> None:
        """Validate interdependent fields after initialization."""
        # Check that hybrid search weights sum to approximately 1.0
        if self.enable_hybrid_search:
            total_weight = (
                self.semantic_weight + self.keyword_weight + self.temporal_weight
            )
            # Allow small floating-point tolerance
            if not (0.99 <= total_weight <= 1.01):
                raise ValueError(
                    f"Hybrid search weights must sum to 1.0 (got {total_weight:.4f}). "
                    f"semantic_weight={self.semantic_weight}, "
                    f"keyword_weight={self.keyword_weight}, "
                    f"temporal_weight={self.temporal_weight}"
                )

    def validate_startup(self) -> list[str]:
        """Validate critical configuration at startup.

        Returns:
            List of validation warnings (empty if all OK)

        Raises:
            ValueError: If critical configuration is invalid
        """
        warnings: list[str] = []

        # Critical: Check required tokens
        if not self.telegram_token or self.telegram_token == "":
            raise ValueError(
                "TELEGRAM_TOKEN is required. Get one from @BotFather on Telegram."
            )

        if not self.gemini_api_key or self.gemini_api_key == "":
            raise ValueError(
                "GEMINI_API_KEY is required. Get one from https://aistudio.google.com/app/apikey"
            )

        # Warn about potentially problematic configurations
        if self.per_user_per_hour < 1:
            warnings.append(
                f"PER_USER_PER_HOUR is {self.per_user_per_hour}, which may cause issues. "
                "Consider using at least 1."
            )

        if self.max_turns > 100:
            warnings.append(
                f"MAX_TURNS is {self.max_turns}, which may cause high token usage. "
                "Consider reducing to 50-70 for better performance."
            )

        if self.context_token_budget > 30000:
            warnings.append(
                f"CONTEXT_TOKEN_BUDGET is {self.context_token_budget}, which is very high. "
                "This may exceed model limits. Consider 8000-16000."
            )

        if self.enable_user_profiling and self.max_facts_per_user > 500:
            warnings.append(
                f"MAX_FACTS_PER_USER is {self.max_facts_per_user}, which may affect performance. "
                "Consider 100-200 for optimal operation."
            )

        # Validate admin user IDs format
        if self.admin_user_ids:
            try:
                self.admin_user_ids_list  # This will raise if format is invalid
            except Exception as e:
                raise ValueError(
                    f"Invalid ADMIN_USER_IDS format: {e}. "
                    "Use comma-separated integers: 123456789,987654321"
                )

        # Check Redis configuration if enabled
        if self.use_redis and not self.redis_url:
            warnings.append(
                "USE_REDIS is true but REDIS_URL is not set. Redis features will be disabled."
            )

        # Check API keys for optional services
        if self.openweather_api_key and len(self.openweather_api_key) < 10:
            warnings.append(
                "OPENWEATHER_API_KEY appears invalid. Weather tools may not work."
            )

        if self.exchange_rate_api_key and len(self.exchange_rate_api_key) < 10:
            warnings.append(
                "EXCHANGE_RATE_API_KEY appears invalid. Currency tools may not work."
            )

        return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
