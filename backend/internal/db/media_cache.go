package db

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
)

// MediaCacheEntry represents a row in the media_cache table.
type MediaCacheEntry struct {
	ID        int64
	MediaID   string
	ChatID    int64
	UserID    *int64
	FilePath  string
	MediaType string
	ExpiresAt time.Time
	CreatedAt time.Time
}

// InsertMediaCache writes data to cacheDir, inserts a row, and returns the new media_id.
// ttlHours is used to set expires_at (e.g. 24 or 48).
func (d *DB) InsertMediaCache(ctx context.Context, cacheDir string, chatID int64, userID *int64, data []byte, ttlHours int) (mediaID string, err error) {
	if ttlHours <= 0 {
		ttlHours = 48
	}
	mediaID = uuid.New().String()
	ext := ".png"
	path := filepath.Join(cacheDir, mediaID+ext)
	if err := os.MkdirAll(cacheDir, 0755); err != nil {
		return "", fmt.Errorf("media cache mkdir: %w", err)
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		return "", fmt.Errorf("media cache write: %w", err)
	}
	absPath, err := filepath.Abs(path)
	if err != nil {
		absPath = path
	}
	expiresAt := time.Now().Add(time.Duration(ttlHours) * time.Hour)
	const query = `
		INSERT INTO media_cache (media_id, chat_id, user_id, file_path, media_type, expires_at)
		VALUES ($1, $2, $3, $4, 'image', $5)`
	_, err = d.pool.ExecContext(ctx, query, mediaID, chatID, userID, absPath, expiresAt)
	if err != nil {
		_ = os.Remove(path)
		return "", fmt.Errorf("media cache insert: %w", err)
	}
	return mediaID, nil
}

// GetMediaCacheByID returns the entry by media_id if not expired. Caller reads file from FilePath.
func (d *DB) GetMediaCacheByID(ctx context.Context, mediaID string) (*MediaCacheEntry, error) {
	const query = `
		SELECT id, media_id, chat_id, user_id, file_path, media_type, expires_at, created_at
		FROM media_cache
		WHERE media_id = $1 AND expires_at > NOW()`
	var e MediaCacheEntry
	var userID sql.NullInt64
	err := d.pool.QueryRowContext(ctx, query, mediaID).Scan(
		&e.ID, &e.MediaID, &e.ChatID, &userID, &e.FilePath, &e.MediaType, &e.ExpiresAt, &e.CreatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get media cache: %w", err)
	}
	if userID.Valid {
		e.UserID = &userID.Int64
	}
	return &e, nil
}
