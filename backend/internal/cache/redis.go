package cache

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/redis/go-redis/v9"
)

const proactiveQueueKey = "proactive:queue"

// Cache wraps the Redis client for rate-limiting and state management.
type Cache struct {
	client *redis.Client
}

// New creates a new Redis cache connection.
func New(addr, password string) (*Cache, error) {
	client := redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: password,
		DB:       0,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping: %w", err)
	}

	slog.Info("redis connected", "addr", addr)
	return &Cache{client: client}, nil
}

// Close shuts down the Redis connection.
func (c *Cache) Close() error {
	return c.client.Close()
}

// Client returns the underlying redis client for advanced use.
func (c *Cache) Client() *redis.Client {
	return c.client
}

// ── Sliding Window Rate Limiter (Section 10) ────────────────────────────

// RateLimitResult holds the outcome of a rate limit check.
type RateLimitResult struct {
	Allowed   bool
	Remaining int
	RetryIn   time.Duration
}

// CheckRateLimit implements a sliding window rate limiter using Redis sorted sets.
// key: the rate limit bucket (e.g., "rl:chat:12345" or "rl:user:67890")
// limit: max allowed requests in the window
// window: the sliding window duration
func (c *Cache) CheckRateLimit(ctx context.Context, key string, limit int, window time.Duration) (*RateLimitResult, error) {
	now := time.Now()
	nowMs := now.UnixMilli()
	windowStartMs := now.Add(-window).UnixMilli()

	// Use a pipeline for atomicity
	pipe := c.client.Pipeline()

	// Remove expired entries outside the window
	pipe.ZRemRangeByScore(ctx, key, "-inf", strconv.FormatInt(windowStartMs, 10))

	// Count current entries in the window
	countCmd := pipe.ZCard(ctx, key)

	// Add the current request
	pipe.ZAdd(ctx, key, redis.Z{
		Score:  float64(nowMs),
		Member: strconv.FormatInt(nowMs, 10),
	})

	// Set TTL on the key to auto-cleanup
	pipe.Expire(ctx, key, window+time.Second)

	_, err := pipe.Exec(ctx)
	if err != nil {
		return nil, fmt.Errorf("rate limit check: %w", err)
	}

	count := int(countCmd.Val())

	if count >= limit {
		// Find the oldest entry to calculate retry time
		oldest, err := c.client.ZRangeWithScores(ctx, key, 0, 0).Result()
		if err != nil || len(oldest) == 0 {
			return &RateLimitResult{Allowed: false, Remaining: 0, RetryIn: window}, nil
		}
		oldestMs := int64(oldest[0].Score)
		retryIn := time.Duration(oldestMs+window.Milliseconds()-nowMs) * time.Millisecond
		if retryIn < 0 {
			retryIn = time.Second
		}

		// Remove the entry we just added since we're denying
		c.client.ZRem(ctx, key, strconv.FormatInt(nowMs, 10))

		return &RateLimitResult{
			Allowed:   false,
			Remaining: 0,
			RetryIn:   retryIn,
		}, nil
	}

	return &RateLimitResult{
		Allowed:   true,
		Remaining: limit - count - 1,
	}, nil
}

// ── Queue Lock (Exclusive Processing per chat, Section 10) ──────────────

// AcquireLock attempts to acquire an exclusive processing lock for a chat.
// Returns true if the lock was acquired, false if another request is already being processed.
func (c *Cache) AcquireLock(ctx context.Context, chatID int64, ttl time.Duration) (bool, error) {
	key := fmt.Sprintf("lock:chat:%d", chatID)
	ok, err := c.client.SetNX(ctx, key, "locked", ttl).Result()
	if err != nil {
		return false, fmt.Errorf("acquire lock: %w", err)
	}
	return ok, nil
}

// ReleaseLock releases the exclusive processing lock for a chat.
func (c *Cache) ReleaseLock(ctx context.Context, chatID int64) error {
	key := fmt.Sprintf("lock:chat:%d", chatID)
	return c.client.Del(ctx, key).Err()

}

// ── Proactive message queue ─────────────────────────────────────────────

// ProactiveItem is one queued proactive message for the frontend to send.
type ProactiveItem struct {
	ChatID int64  `json:"chat_id"`
	Reply  string `json:"reply"`
}

// PushProactive pushes a proactive message onto the queue (frontend will pop and send to Telegram).
func (c *Cache) PushProactive(ctx context.Context, item ProactiveItem) error {
	b, err := json.Marshal(item)
	if err != nil {
		return err
	}
	return c.client.LPush(ctx, proactiveQueueKey, string(b)).Err()
}

// PopProactive blocks up to timeout for an item; returns (chatID, reply, true) or (0, "", false).
func (c *Cache) PopProactive(ctx context.Context, timeout time.Duration) (chatID int64, reply string, ok bool) {
	result, err := c.client.BRPop(ctx, timeout, proactiveQueueKey).Result()
	if err != nil || len(result) != 2 {
		return 0, "", false
	}
	var item ProactiveItem
	if json.Unmarshal([]byte(result[1]), &item) != nil {
		return 0, "", false
	}
	return item.ChatID, item.Reply, true
}
