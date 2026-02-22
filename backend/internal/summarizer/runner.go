package summarizer

import (
	"context"
	"errors"
	"log/slog"
	"strconv"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/cache"
	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"github.com/ThatHunky/gryag/backend/internal/llm"
	"github.com/redis/go-redis/v9"
)

const (
	lastRunKey7day  = "summary:last_run:7day"
	lastRunKey30day = "summary:last_run:30day"
)

// Runner runs summarization for 7-day or 30-day windows.
type Runner struct {
	db     *db.DB
	cache  *cache.Cache
	llm    *llm.Client
	config *config.Config
}

// NewRunner creates a summarizer runner.
func NewRunner(database *db.DB, c *cache.Cache, llmClient *llm.Client, cfg *config.Config) *Runner {
	return &Runner{db: database, cache: c, llm: llmClient, config: cfg}
}

// RunOne runs summarization for the given type ("7day" or "30day") for all eligible chats.
func (r *Runner) RunOne(ctx context.Context, summaryType string) {
	logger := slog.With("component", "summarizer", "summary_type", summaryType)
	var since time.Duration
	var windowLabel string
	var periodStart, periodEnd time.Time
	if summaryType == "7day" {
		since = 7 * 24 * time.Hour
		windowLabel = "7-day"
		periodEnd = time.Now()
		periodStart = periodEnd.Add(-since)
	} else if summaryType == "30day" {
		since = 30 * 24 * time.Hour
		windowLabel = "30-day"
		periodEnd = time.Now()
		periodStart = periodEnd.Add(-since)
	} else {
		logger.Warn("unknown summary type, skipping")
		return
	}

	chatIDs, err := r.db.GetRecentChatIDs(ctx, since)
	if err != nil {
		logger.Error("failed to get recent chat IDs", "error", err)
		return
	}
	if len(chatIDs) == 0 {
		logger.Info("no chats to summarize")
		return
	}

	limit := r.config.SummaryMaxMessagesPerWindow
	if limit <= 0 {
		limit = 2000
	}

	for _, chatID := range chatIDs {
		messages, err := r.db.GetMessagesInRange(ctx, chatID, periodStart, periodEnd, limit)
		if err != nil {
			logger.Error("get messages in range failed", "chat_id", chatID, "error", err)
			continue
		}
		if len(messages) == 0 {
			continue
		}
		summary, err := r.llm.SummarizeChat(ctx, messages, windowLabel)
		if err != nil {
			logger.Error("summarize chat failed", "chat_id", chatID, "error", err)
			continue
		}
		if summary == "" {
			continue
		}
		_, err = r.db.InsertChatSummary(ctx, chatID, summaryType, summary, periodStart, periodEnd)
		if err != nil {
			logger.Error("insert chat summary failed", "chat_id", chatID, "error", err)
			continue
		}
		logger.Info("summary stored", "chat_id", chatID, "messages", len(messages))
	}
}

// SetLastRun records the last run time for the given summary type in Redis.
func (r *Runner) SetLastRun(ctx context.Context, summaryType string) error {
	key := lastRunKey7day
	if summaryType == "30day" {
		key = lastRunKey30day
	}
	return r.cache.Client().Set(ctx, key, time.Now().Unix(), 0).Err()
}

// GetLastRun returns the last run Unix timestamp for the given type, or 0 if never run.
func (r *Runner) GetLastRun(ctx context.Context, summaryType string) (int64, error) {
	key := lastRunKey7day
	if summaryType == "30day" {
		key = lastRunKey30day
	}
	val, err := r.cache.Client().Get(ctx, key).Result()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return 0, nil
		}
		return 0, err
	}
	t, _ := strconv.ParseInt(val, 10, 64)
	return t, nil
}
