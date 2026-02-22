package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"runtime"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
)

// AdminHandler provides management endpoints for bot administrators.
type AdminHandler struct {
	db     *db.DB
	config *config.Config
	startTime time.Time
}

// NewAdminHandler creates a new admin handler.
func NewAdminHandler(cfg *config.Config, database *db.DB) *AdminHandler {
	return &AdminHandler{
		db:        database,
		config:    cfg,
		startTime: time.Now(),
	}
}

// isAdmin checks if the requesting user is an admin.
func (a *AdminHandler) isAdmin(userID int64) bool {
	for _, id := range a.config.AdminIDs {
		if id == userID {
			return true
		}
	}
	return false
}

// Stats returns server statistics.
func (a *AdminHandler) Stats(w http.ResponseWriter, r *http.Request) {
	requestID := r.Header.Get("X-Request-ID")

	var req struct {
		UserID int64 `json:"user_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
		return
	}

	if !a.isAdmin(req.UserID) {
		slog.Warn("unauthorized admin access attempt", "user_id", req.UserID, "request_id", requestID)
		http.Error(w, `{"error":"unauthorized"}`, http.StatusForbidden)
		return
	}

	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	stats := map[string]any{
		"uptime":          time.Since(a.startTime).String(),
		"uptime_seconds":  time.Since(a.startTime).Seconds(),
		"go_version":      runtime.Version(),
		"goroutines":      runtime.NumGoroutine(),
		"memory_alloc_mb": float64(m.Alloc) / 1024 / 1024,
		"memory_sys_mb":   float64(m.Sys) / 1024 / 1024,
		"gc_cycles":       m.NumGC,
		"gemini_model":    a.config.GeminiModel,
		"default_lang":    a.config.DefaultLang,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

// ReloadPersona re-reads the persona file from disk (hot-swap).
func (a *AdminHandler) ReloadPersona(w http.ResponseWriter, r *http.Request) {
	requestID := r.Header.Get("X-Request-ID")

	var req struct {
		UserID int64 `json:"user_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
		return
	}

	if !a.isAdmin(req.UserID) {
		slog.Warn("unauthorized persona reload attempt", "user_id", req.UserID, "request_id", requestID)
		http.Error(w, `{"error":"unauthorized"}`, http.StatusForbidden)
		return
	}

	// Verify the persona file is readable
	if _, err := os.ReadFile(a.config.PersonaFile); err != nil {
		slog.Error("persona file not readable", "path", a.config.PersonaFile, "error", err)
		http.Error(w, `{"error":"persona file not readable"}`, http.StatusInternalServerError)
		return
	}

	slog.Info("persona reload requested", "user_id", req.UserID, "path", a.config.PersonaFile)

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"message": "Persona will be reloaded on next request.",
		"file":    a.config.PersonaFile,
	})
}
