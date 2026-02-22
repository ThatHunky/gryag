package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config holds all application configuration parsed from environment variables.
type Config struct {
	// Telegram
	TelegramBotToken  string
	AdminIDs          []int64
	AllowedChatIDs    []int64 // optional; empty = allow all chats

	// Gemini
	GeminiAPIKey             string
	GeminiModel              string
	GeminiTemperature        float64
	GeminiRoutingTemperature float64
	GeminiThinkingBudget     int

	// OpenAI (Optional)
	OpenAIAPIKey string
	OpenAIModel  string

	// PostgreSQL
	PostgresHost     string
	PostgresPort     int
	PostgresUser     string
	PostgresPassword string
	PostgresDB       string

	// Redis
	RedisHost     string
	RedisPort     int
	RedisPassword string

	// Backend Server
	BackendHost string
	BackendPort int

	// Feature Toggles
	EnableSandbox           bool
	EnableImageGeneration   bool
	EnableProactiveMessaging bool
	EnableWebSearch         bool
	EnableVoiceSTT          bool

	// Rate Limiting
	RateLimitGlobalPerMinute int
	RateLimitUserPerMinute   int
	RateLimitImagePerDay     int
	RateLimitSandboxPerDay   int

	// Sandbox
	SandboxTimeoutSeconds int
	SandboxMaxMemoryMB    int

	// Proactive Messaging (Kyiv time)
	ProactiveActiveStartHour int // 0-23, inclusive
	ProactiveActiveEndHour   int // 0-23, exclusive (e.g. 9-22 means 09:00–21:59)

	// Context Window
	ImmediateContextSize int
	MediaBufferMax       int

	// Data Retention
	MessageRetentionDays int

	// Media cache (generated images for edit by media_id)
	MediaCacheDir      string
	MediaCacheTTLHours int

	// Persona
	PersonaFile string

	// Telegram Mode
	TelegramMode  string
	WebhookURL    string
	WebhookSecret string

	// Localization
	LocaleDir   string
	DefaultLang string
}

// Load reads all configuration from environment variables.
func Load() (*Config, error) {
	cfg := &Config{
		// Telegram
		TelegramBotToken: getEnv("TELEGRAM_BOT_TOKEN", ""),
		AdminIDs:         parseAdminIDs(getEnv("ADMIN_IDS", "")),
		AllowedChatIDs:   parseAdminIDs(getEnv("ALLOWED_CHAT_IDS", "")),

		// Gemini
		GeminiAPIKey:             getEnv("GEMINI_API_KEY", ""),
		GeminiModel:              getEnv("GEMINI_MODEL", "gemini-2.5-flash"),
		GeminiTemperature:        getEnvFloat("GEMINI_TEMPERATURE", 0.9),
		GeminiRoutingTemperature: getEnvFloat("GEMINI_ROUTING_TEMPERATURE", 0.0),
		GeminiThinkingBudget:     getEnvInt("GEMINI_THINKING_BUDGET", 0),

		// OpenAI
		OpenAIAPIKey: getEnv("OPENAI_API_KEY", ""),
		OpenAIModel:  getEnv("OPENAI_MODEL", "gpt-4o-mini"),

		// PostgreSQL
		PostgresHost:     getEnv("POSTGRES_HOST", "gryag-postgres"),
		PostgresPort:     getEnvInt("POSTGRES_PORT", 5432),
		PostgresUser:     getEnv("POSTGRES_USER", "gryag"),
		PostgresPassword: getEnv("POSTGRES_PASSWORD", "changeme_in_production"),
		PostgresDB:       getEnv("POSTGRES_DB", "gryag"),

		// Redis
		RedisHost:     getEnv("REDIS_HOST", "gryag-redis"),
		RedisPort:     getEnvInt("REDIS_PORT", 6379),
		RedisPassword: getEnv("REDIS_PASSWORD", ""),

		// Backend Server
		BackendHost: getEnv("BACKEND_HOST", "0.0.0.0"),
		BackendPort: getEnvInt("BACKEND_PORT", 27710),

		// Feature Toggles
		EnableSandbox:           getEnvBool("ENABLE_SANDBOX", true),
		EnableImageGeneration:   getEnvBool("ENABLE_IMAGE_GENERATION", true),
		EnableProactiveMessaging: getEnvBool("ENABLE_PROACTIVE_MESSAGING", false),
		EnableWebSearch:         getEnvBool("ENABLE_WEB_SEARCH", true),
		EnableVoiceSTT:          getEnvBool("ENABLE_VOICE_STT", false),

		// Rate Limiting
		RateLimitGlobalPerMinute: getEnvInt("RATE_LIMIT_GLOBAL_PER_MINUTE", 10),
		RateLimitUserPerMinute:   getEnvInt("RATE_LIMIT_USER_PER_MINUTE", 3),
		RateLimitImagePerDay:     getEnvInt("RATE_LIMIT_IMAGE_PER_DAY", 5),
		RateLimitSandboxPerDay:   getEnvInt("RATE_LIMIT_SANDBOX_PER_DAY", 20),

		// Sandbox
		SandboxTimeoutSeconds: getEnvInt("SANDBOX_TIMEOUT_SECONDS", 5),
		SandboxMaxMemoryMB:    getEnvInt("SANDBOX_MAX_MEMORY_MB", 128),

		// Proactive Messaging (active hours in Kyiv time; parsed below)
		ProactiveActiveStartHour: 9,
		ProactiveActiveEndHour:   22,

		// Context Window
		ImmediateContextSize: getEnvInt("IMMEDIATE_CONTEXT_SIZE", 50),
		MediaBufferMax:       getEnvInt("MEDIA_BUFFER_MAX", 10),

		// Data Retention
		MessageRetentionDays: getEnvInt("MESSAGE_RETENTION_DAYS", 90),

		// Media cache (generated images, TTL for edit by media_id)
		MediaCacheDir:      getEnv("MEDIA_CACHE_DIR", "/tmp/gryag_media_cache"),
		MediaCacheTTLHours: getEnvInt("MEDIA_CACHE_TTL_HOURS", 48),

		// Persona
		PersonaFile: getEnv("PERSONA_FILE", "config/persona.txt"),

		// Telegram Mode
		TelegramMode:  getEnv("TELEGRAM_MODE", "polling"),
		WebhookURL:    getEnv("WEBHOOK_URL", ""),
		WebhookSecret: getEnv("WEBHOOK_SECRET", ""),

		// Localization
		LocaleDir:   getEnv("LOCALE_DIR", "config/locales"),
		DefaultLang: getEnv("DEFAULT_LANG", "uk"),
	}
	parseProactiveActiveHours(getEnv("PROACTIVE_ACTIVE_HOURS_KYIV", "9-22"), cfg)

	// Validate required fields
	if cfg.GeminiAPIKey == "" {
		return nil, fmt.Errorf("GEMINI_API_KEY is required")
	}

	return cfg, nil
}

// PostgresDSN returns the PostgreSQL connection string.
func (c *Config) PostgresDSN() string {
	return fmt.Sprintf(
		"postgres://%s:%s@%s:%d/%s?sslmode=disable",
		c.PostgresUser, c.PostgresPassword,
		c.PostgresHost, c.PostgresPort,
		c.PostgresDB,
	)
}

// RedisAddr returns the Redis connection address.
func (c *Config) RedisAddr() string {
	return fmt.Sprintf("%s:%d", c.RedisHost, c.RedisPort)
}

// ListenAddr returns the backend server listen address.
func (c *Config) ListenAddr() string {
	return fmt.Sprintf("%s:%d", c.BackendHost, c.BackendPort)
}

// --- helpers ---

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	i, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return i
}

func getEnvFloat(key string, fallback float64) float64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	f, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return fallback
	}
	return f
}

func getEnvBool(key string, fallback bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return fallback
	}
	return b
}

func parseAdminIDs(raw string) []int64 {
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	ids := make([]int64, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if id, err := strconv.ParseInt(p, 10, 64); err == nil {
			ids = append(ids, id)
		}
	}
	return ids
}

// parseProactiveActiveHours sets cfg.ProactiveActiveStartHour and ProactiveActiveEndHour from
// a string like "9-22" (09:00–22:00 Kyiv) or "22-6" (22:00–06:00 overnight). End is exclusive.
func parseProactiveActiveHours(raw string, cfg *Config) {
	raw = strings.TrimSpace(raw)
	parts := strings.Split(raw, "-")
	if len(parts) != 2 {
		return
	}
	start, err1 := strconv.Atoi(strings.TrimSpace(parts[0]))
	end, err2 := strconv.Atoi(strings.TrimSpace(parts[1]))
	if err1 != nil || err2 != nil {
		return
	}
	if start >= 0 && start <= 23 && end >= 0 && end <= 23 {
		cfg.ProactiveActiveStartHour = start
		cfg.ProactiveActiveEndHour = end
	}
}
