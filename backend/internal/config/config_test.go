package config

import (
	"os"
	"testing"
)

func TestLoad_Defaults(t *testing.T) {
	// Set only the required field
	os.Setenv("GEMINI_API_KEY", "test-key")
	defer os.Unsetenv("GEMINI_API_KEY")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.GeminiModel != "gemini-2.5-flash" {
		t.Errorf("expected model 'gemini-2.5-flash', got '%s'", cfg.GeminiModel)
	}
	if cfg.BackendPort != 27710 {
		t.Errorf("expected port 27710, got %d", cfg.BackendPort)
	}
	if cfg.RateLimitGlobalPerMinute != 10 {
		t.Errorf("expected global rate limit 10, got %d", cfg.RateLimitGlobalPerMinute)
	}
	if cfg.RateLimitUserPerMinute != 3 {
		t.Errorf("expected user rate limit 3, got %d", cfg.RateLimitUserPerMinute)
	}
	if !cfg.EnableSandbox {
		t.Error("expected EnableSandbox to be true by default")
	}
	if !cfg.EnableImageGeneration {
		t.Error("expected EnableImageGeneration to be true by default")
	}
	if cfg.EnableProactiveMessaging {
		t.Error("expected EnableProactiveMessaging to be false by default")
	}
	if cfg.PersonaFile != "config/persona.txt" {
		t.Errorf("expected persona file 'config/persona.txt', got '%s'", cfg.PersonaFile)
	}
	if cfg.TelegramMode != "polling" {
		t.Errorf("expected telegram mode 'polling', got '%s'", cfg.TelegramMode)
	}
}

func TestLoad_MissingAPIKey(t *testing.T) {
	os.Unsetenv("GEMINI_API_KEY")

	_, err := Load()
	if err == nil {
		t.Fatal("expected error for missing GEMINI_API_KEY")
	}
}

func TestLoad_CustomValues(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "custom-key")
	os.Setenv("GEMINI_MODEL", "gemini-2.0-pro")
	os.Setenv("BACKEND_PORT", "9090")
	os.Setenv("RATE_LIMIT_GLOBAL_PER_MINUTE", "20")
	os.Setenv("ENABLE_SANDBOX", "false")
	os.Setenv("ADMIN_IDS", "111,222,333")
	defer func() {
		os.Unsetenv("GEMINI_API_KEY")
		os.Unsetenv("GEMINI_MODEL")
		os.Unsetenv("BACKEND_PORT")
		os.Unsetenv("RATE_LIMIT_GLOBAL_PER_MINUTE")
		os.Unsetenv("ENABLE_SANDBOX")
		os.Unsetenv("ADMIN_IDS")
	}()

	cfg, err := Load()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.GeminiModel != "gemini-2.0-pro" {
		t.Errorf("expected 'gemini-2.0-pro', got '%s'", cfg.GeminiModel)
	}
	if cfg.BackendPort != 9090 {
		t.Errorf("expected 9090, got %d", cfg.BackendPort)
	}
	if cfg.RateLimitGlobalPerMinute != 20 {
		t.Errorf("expected 20, got %d", cfg.RateLimitGlobalPerMinute)
	}
	if cfg.EnableSandbox {
		t.Error("expected EnableSandbox to be false")
	}
	if len(cfg.AdminIDs) != 3 || cfg.AdminIDs[0] != 111 || cfg.AdminIDs[1] != 222 || cfg.AdminIDs[2] != 333 {
		t.Errorf("expected admin IDs [111 222 333], got %v", cfg.AdminIDs)
	}
}

func TestPostgresDSN(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	defer os.Unsetenv("GEMINI_API_KEY")

	cfg, _ := Load()
	dsn := cfg.PostgresDSN()

	expected := "postgres://gryag:changeme_in_production@gryag-postgres:5432/gryag?sslmode=disable"
	if dsn != expected {
		t.Errorf("expected DSN '%s', got '%s'", expected, dsn)
	}
}

func TestRedisAddr(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	defer os.Unsetenv("GEMINI_API_KEY")

	cfg, _ := Load()
	addr := cfg.RedisAddr()

	if addr != "gryag-redis:6379" {
		t.Errorf("expected 'gryag-redis:6379', got '%s'", addr)
	}
}
