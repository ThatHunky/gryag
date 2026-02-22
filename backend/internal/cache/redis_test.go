package cache

import (
	"context"
	"os"
	"testing"
	"time"
)

// These tests require a running Redis instance.
// Skip if REDIS_TEST_ADDR is not set (e.g., in CI without Redis).
func getTestCache(t *testing.T) *Cache {
	t.Helper()
	addr := os.Getenv("REDIS_TEST_ADDR")
	if addr == "" {
		addr = "localhost:6379"
	}
	c, err := New(addr, "")
	if err != nil {
		t.Skipf("skipping redis tests: %v", err)
	}
	t.Cleanup(func() { c.Close() })
	return c
}

func TestCheckRateLimit_AllowsUnderLimit(t *testing.T) {
	c := getTestCache(t)
	ctx := context.Background()
	key := "test:rl:under:" + t.Name()
	defer c.Client().Del(ctx, key)

	result, err := c.CheckRateLimit(ctx, key, 5, time.Minute)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.Allowed {
		t.Error("expected request to be allowed")
	}
	if result.Remaining != 4 {
		t.Errorf("expected 4 remaining, got %d", result.Remaining)
	}
}

func TestCheckRateLimit_BlocksOverLimit(t *testing.T) {
	c := getTestCache(t)
	ctx := context.Background()
	key := "test:rl:over:" + t.Name()
	defer c.Client().Del(ctx, key)

	// Fill up the limit
	for i := 0; i < 3; i++ {
		result, err := c.CheckRateLimit(ctx, key, 3, time.Minute)
		if err != nil {
			t.Fatalf("request %d: unexpected error: %v", i, err)
		}
		if !result.Allowed {
			t.Fatalf("request %d: expected to be allowed", i)
		}
	}

	// 4th request should be blocked
	result, err := c.CheckRateLimit(ctx, key, 3, time.Minute)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Allowed {
		t.Error("expected request to be blocked")
	}
	if result.Remaining != 0 {
		t.Errorf("expected 0 remaining, got %d", result.Remaining)
	}
	if result.RetryIn <= 0 {
		t.Error("expected positive RetryIn")
	}
}

func TestAcquireLock_ExclusiveProcessing(t *testing.T) {
	c := getTestCache(t)
	ctx := context.Background()
	chatID := int64(99999)
	defer c.Client().Del(ctx, "lock:chat:99999")

	// First lock should succeed
	ok, err := c.AcquireLock(ctx, chatID, 30*time.Second)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !ok {
		t.Error("expected lock to be acquired")
	}

	// Second lock should fail (already locked)
	ok2, err := c.AcquireLock(ctx, chatID, 30*time.Second)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if ok2 {
		t.Error("expected lock to be denied (already locked)")
	}

	// Release and re-acquire
	if err := c.ReleaseLock(ctx, chatID); err != nil {
		t.Fatalf("release error: %v", err)
	}
	ok3, err := c.AcquireLock(ctx, chatID, 30*time.Second)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !ok3 {
		t.Error("expected lock to be acquired after release")
	}
}
