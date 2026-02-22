package main

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/config"
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
	)

	// ── HTTP Mux ────────────────────────────────────────────────────────
	mux := http.NewServeMux()

	// Health check (Section 15.2)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{
			"status": "ok",
			"time":   time.Now().UTC().Format(time.RFC3339),
		})
	})

	// Stub process endpoint — the main entry point from the Python frontend
	mux.HandleFunc("POST /api/v1/process", func(w http.ResponseWriter, r *http.Request) {
		requestID := r.Header.Get("X-Request-ID")
		logger := slog.With("request_id", requestID)

		// Decode the incoming payload
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			logger.Warn("invalid request payload", "error", err)
			http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
			return
		}
		defer r.Body.Close()

		logger.Info("received process request",
			"chat_id", payload["chat_id"],
			"user_id", payload["user_id"],
		)

		// Stub response — will be replaced with actual Gemini integration in Phase 3
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"reply":      "Backend stub: message received.",
			"request_id": requestID,
		})
	})

	// ── Start Server ────────────────────────────────────────────────────
	addr := cfg.ListenAddr()
	slog.Info("starting gryag-backend", "addr", addr)

	server := &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 60 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	if err := server.ListenAndServe(); err != nil {
		slog.Error("server failed", "error", err)
		os.Exit(1)
	}
}
