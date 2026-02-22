package middleware

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/cache"
	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
)

// RateLimiter is an HTTP middleware that enforces tiered rate limiting
// and exclusive queue locking per Section 10 of the architecture.
type RateLimiter struct {
	cache  *cache.Cache
	db     *db.DB
	config *config.Config
}

// NewRateLimiter creates a new rate limiting middleware.
func NewRateLimiter(c *cache.Cache, d *db.DB, cfg *config.Config) *RateLimiter {
	return &RateLimiter{
		cache:  c,
		db:     d,
		config: cfg,
	}
}

// Middleware returns the HTTP middleware handler.
// When a request is throttled:
//   - The bot stays SILENT (no error response — Section 10)
//   - The message is still logged to PostgreSQL for context
func (rl *RateLimiter) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestID := r.Header.Get("X-Request-ID")
		logger := slog.With("request_id", requestID)

		// Read the full body so we can both parse it here and pass it downstream.
		bodyBytes, err := io.ReadAll(r.Body)
		r.Body.Close()
		if err != nil {
			logger.Warn("failed to read request body", "error", err)
			http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
			return
		}

		var payload struct {
			ChatID int64  `json:"chat_id"`
			UserID *int64 `json:"user_id"`
			Text   string `json:"text"`
		}
		if err := json.Unmarshal(bodyBytes, &payload); err != nil {
			http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
			return
		}

		ctx := r.Context()

		// ── Check 0: Chat/group whitelist (if configured) ───────────────
		if len(rl.config.AllowedChatIDs) > 0 {
			allowed := false
			for _, id := range rl.config.AllowedChatIDs {
				if id == payload.ChatID {
					allowed = true
					break
				}
			}
			if !allowed {
				logger.Info("chat_not_allowed", "chat_id", payload.ChatID)
				w.WriteHeader(http.StatusNoContent)
				return
			}
		}

		// ── Check 1: Global Chat Rate Limit ───────────────────────────
		chatKey := fmt.Sprintf("rl:chat:%d", payload.ChatID)
		chatResult, err := rl.cache.CheckRateLimit(ctx, chatKey, rl.config.RateLimitGlobalPerMinute, time.Minute)
		if err != nil {
			logger.Error("chat rate limit check failed", "error", err)
			// On error, allow the request through (fail-open for rate limiting)
		} else if !chatResult.Allowed {
			logger.Info("throttled_chat",
				"chat_id", payload.ChatID,
				"retry_in", chatResult.RetryIn,
			)
			rl.logThrottledMessage(ctx, payload.ChatID, payload.UserID, payload.Text, requestID)
			// Strict silence — return 204 No Content (Section 10)
			w.WriteHeader(http.StatusNoContent)
			return
		}

		// ── Check 2: Per-User Rate Limit ──────────────────────────────
		if payload.UserID != nil {
			userKey := fmt.Sprintf("rl:user:%d:%d", payload.ChatID, *payload.UserID)
			userResult, err := rl.cache.CheckRateLimit(ctx, userKey, rl.config.RateLimitUserPerMinute, time.Minute)
			if err != nil {
				logger.Error("user rate limit check failed", "error", err)
			} else if !userResult.Allowed {
				logger.Info("throttled_user",
					"user_id", *payload.UserID,
					"chat_id", payload.ChatID,
					"retry_in", userResult.RetryIn,
				)
				rl.logThrottledMessage(ctx, payload.ChatID, payload.UserID, payload.Text, requestID)
				w.WriteHeader(http.StatusNoContent)
				return
			}
		}

		// ── Check 3: Queue Lock (Exclusive Processing) ────────────────
		locked, err := rl.cache.AcquireLock(ctx, payload.ChatID, 2*time.Minute)
		if err != nil {
			logger.Error("queue lock check failed", "error", err)
		} else if !locked {
			logger.Info("queue_locked",
				"chat_id", payload.ChatID,
			)
			rl.logThrottledMessage(ctx, payload.ChatID, payload.UserID, payload.Text, requestID)
			w.WriteHeader(http.StatusNoContent)
			return
		}

		// Ensure the lock is released when processing completes
		defer func() {
			if err := rl.cache.ReleaseLock(ctx, payload.ChatID); err != nil {
				logger.Error("failed to release queue lock", "error", err)
			}
		}()

		// Restore body for downstream handler (Process needs full JSON).
		// Do this after WithContext so the request we pass has the body set.
		ctx = context.WithValue(ctx, payloadKey{}, payload)
		r = r.WithContext(ctx)
		r.Body = io.NopCloser(bytes.NewReader(bodyBytes))
		r.ContentLength = int64(len(bodyBytes))

		// Pass through to the actual handler
		next.ServeHTTP(w, r)
	})
}

// logThrottledMessage writes a throttled message to PostgreSQL for context (Section 10).
func (rl *RateLimiter) logThrottledMessage(ctx context.Context, chatID int64, userID *int64, text, requestID string) {
	msg := &db.Message{
		ChatID:       chatID,
		UserID:       userID,
		Text:         &text,
		RequestID:    &requestID,
		WasThrottled: true,
	}
	if _, err := rl.db.InsertMessage(ctx, msg); err != nil {
		slog.Error("failed to log throttled message", "error", err)
	}
}

// payloadKey is a context key for the parsed request payload.
type payloadKey struct{}

// GetPayload retrieves the parsed payload from the request context.
func GetPayload(ctx context.Context) (chatID int64, userID *int64, text string, ok bool) {
	p, exists := ctx.Value(payloadKey{}).(struct {
		ChatID int64  `json:"chat_id"`
		UserID *int64 `json:"user_id"`
		Text   string `json:"text"`
	})
	if !exists {
		return 0, nil, "", false
	}
	return p.ChatID, p.UserID, p.Text, true
}
