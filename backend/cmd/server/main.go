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
	"github.com/ThatHunky/gryag/backend/internal/proactive"
	"github.com/ThatHunky/gryag/backend/internal/summarizer"
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

	// ── Run Migrations ─────────────────────────────────────────────────
	if err := db.RunMigrations(database.Pool(), "migrations"); err != nil {
		slog.Error("failed to run migrations", "error", err)
		os.Exit(1)
	}

	// ── Message Retention Cleanup ───────────────────────────────────────
	if _, err := database.PruneOldMessages(context.Background(), cfg.MessageRetentionDays); err != nil {
		slog.Warn("message retention cleanup failed", "error", err)
	}

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
	executor := tools.NewExecutor(cfg, database, bundle, llmClient)
	slog.Info("tools loaded", "count", registry.Count(), "names", registry.GetToolNames())

	// ── Request Handler ─────────────────────────────────────────────────
	h := handler.New(cfg, database, redisCache, llmClient, registry, executor, bundle)

	// ── Rate Limiter Middleware ──────────────────────────────────────────
	rateLimiter := middleware.NewRateLimiter(redisCache, database, cfg)

	// ── Admin Handler ───────────────────────────────────────────────────
	adminH := handler.NewAdminHandler(cfg, database)

	// ── Proactive messaging (optional) ───────────────────────────────────
	if cfg.EnableProactiveMessaging {
		proactiveRunner := proactive.NewRunner(cfg, database, llmClient, registry, executor, redisCache)
		go proactive.Scheduler(context.Background(), proactiveRunner, cfg.ProactiveActiveStartHour, cfg.ProactiveActiveEndHour)
		slog.Info("proactive messaging started", "active_hours_start", cfg.ProactiveActiveStartHour, "active_hours_end", cfg.ProactiveActiveEndHour)
	}

	// ── Summarization (optional; 3 AM Kyiv, 7-day every 3 days, 30-day every 12 days) ──
	if cfg.EnableSummarization {
		summarizerRunner := summarizer.NewRunner(database, redisCache, llmClient, cfg)
		go summarizer.Scheduler(context.Background(), summarizerRunner, cfg)
		slog.Info("summarization started", "run_hour_kyiv", cfg.SummaryRunHour, "7day_interval_days", cfg.Summary7DayIntervalDays, "30day_interval_days", cfg.Summary30DayIntervalDays)
	}

	// ── HTTP Mux ────────────────────────────────────────────────────────
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", handler.HealthCheck)
	mux.Handle("POST /api/v1/process", rateLimiter.Middleware(http.HandlerFunc(h.Process)))
	mux.HandleFunc("POST /api/v1/admin/stats", adminH.Stats)
	mux.HandleFunc("POST /api/v1/admin/reload_persona", adminH.ReloadPersona)
	if cfg.EnableProactiveMessaging {
		mux.HandleFunc("GET /api/v1/proactive", h.Proactive)
	}

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
