package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/cache"
	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"github.com/ThatHunky/gryag/backend/internal/handler"
	"github.com/ThatHunky/gryag/backend/internal/i18n"
	"github.com/ThatHunky/gryag/backend/internal/llm"
	"github.com/ThatHunky/gryag/backend/internal/middleware"
	"github.com/ThatHunky/gryag/backend/internal/tools"
)

func main() {
	// ── Structured JSON Logger ──────────────────────────────────────────
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	// ── Load Configuration ──────────────────────────────────────────────
	cfg, err := config.Load()
	if err != nil {
		slog.Error("failed to load configuration", "error", err)
		os.Exit(1)
	}
	slog.Info("configuration loaded",
		"model", cfg.GeminiModel,
		"backend_addr", cfg.ListenAddr(),
		"postgres", cfg.PostgresHost,
		"redis", cfg.RedisAddr(),
		"locale_dir", cfg.LocaleDir,
		"default_lang", cfg.DefaultLang,
	)

	// ── i18n Bundle ─────────────────────────────────────────────────────
	bundle, err := i18n.NewBundle(cfg.LocaleDir, cfg.DefaultLang)
	if err != nil {
		slog.Error("failed to load i18n locales", "error", err)
		os.Exit(1)
	}
	slog.Info("i18n loaded", "languages", bundle.Languages())

	// ── PostgreSQL ──────────────────────────────────────────────────────
	database, err := db.New(cfg.PostgresDSN())
	if err != nil {
		slog.Error("failed to connect to postgres", "error", err)
		os.Exit(1)
	}
	defer database.Close()

	// ── Redis ───────────────────────────────────────────────────────────
	redisCache, err := cache.New(cfg.RedisAddr(), cfg.RedisPassword)
	if err != nil {
		slog.Error("failed to connect to redis", "error", err)
		os.Exit(1)
	}
	defer redisCache.Close()

	// ── Gemini LLM Client ───────────────────────────────────────────────
	llmClient, err := llm.NewClient(cfg)
	if err != nil {
		slog.Error("failed to initialize gemini client", "error", err)
		os.Exit(1)
	}

	// ── Tool Registry & Executor ────────────────────────────────────────
	registry := tools.NewRegistry(cfg)
	executor := tools.NewExecutor(cfg, database, bundle)
	slog.Info("tools loaded", "count", registry.Count(), "names", registry.GetToolNames())

	// ── Request Handler ─────────────────────────────────────────────────
	h := handler.New(cfg, database, redisCache, llmClient, registry, executor)

	// ── Rate Limiter Middleware ──────────────────────────────────────────
	rateLimiter := middleware.NewRateLimiter(redisCache, database, cfg)

	// ── HTTP Mux ────────────────────────────────────────────────────────
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handler.HealthCheck)
	mux.Handle("POST /api/v1/process", rateLimiter.Middleware(http.HandlerFunc(h.Process)))

	// ── Server with Graceful Shutdown ────────────────────────────────────
	addr := cfg.ListenAddr()
	server := &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 120 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	// Start server in a goroutine
	go func() {
		slog.Info("starting gryag-backend", "addr", addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()

	// Wait for interrupt signal for graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	sig := <-quit
	slog.Info("shutting down", "signal", sig.String())

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		slog.Error("server forced shutdown", "error", err)
	}

	slog.Info("server stopped")
}
