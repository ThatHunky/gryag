package db

import (
	"context"
	"fmt"
	"log/slog"
)

// PruneOldMessages deletes messages older than retentionDays.
// Called on startup to enforce the configured retention policy.
func (d *DB) PruneOldMessages(ctx context.Context, retentionDays int) (int64, error) {
	if retentionDays <= 0 {
		slog.Info("message retention disabled (0 days = keep forever)")
		return 0, nil
	}

	result, err := d.pool.ExecContext(ctx,
		"DELETE FROM messages WHERE created_at < NOW() - INTERVAL '1 day' * $1",
		retentionDays,
	)
	if err != nil {
		return 0, fmt.Errorf("prune old messages: %w", err)
	}

	count, _ := result.RowsAffected()
	if count > 0 {
		slog.Info("pruned old messages", "deleted", count, "retention_days", retentionDays)
	}
	return count, nil
}
