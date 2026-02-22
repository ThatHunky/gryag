package db

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"time"

	_ "github.com/lib/pq"
)

// Message represents a single stored message.
type Message struct {
	ID           int64
	ChatID       int64
	UserID       *int64
	Username     *string
	FirstName    *string
	Text         *string
	MessageID    *int64
	MediaType    *string
	IsBotReply   bool
	RequestID    *string
	WasThrottled bool
	CreatedAt    time.Time
}

// UserFact represents a stored fact about a user.
type UserFact struct {
	ID        int64
	ChatID    int64
	UserID    int64
	FactText  string
	CreatedAt time.Time
	UpdatedAt time.Time
}

// DB wraps the PostgreSQL connection pool.
type DB struct {
	pool *sql.DB
}

// New creates a new DB connection pool.
func New(dsn string) (*DB, error) {
	pool, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("db open: %w", err)
	}

	pool.SetMaxOpenConns(25)
	pool.SetMaxIdleConns(5)
	pool.SetConnMaxLifetime(5 * time.Minute)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := pool.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("db ping: %w", err)
	}

	slog.Info("postgres connected")
	return &DB{pool: pool}, nil
}

// Close shuts down the connection pool.
func (d *DB) Close() error {
	return d.pool.Close()
}

// Pool returns the underlying *sql.DB for use in tests or migrations.
func (d *DB) Pool() *sql.DB {
	return d.pool
}

// ── Message Operations ──────────────────────────────────────────────────

// InsertMessage stores a message in the log. Throttled messages use wasThrottled=true.
func (d *DB) InsertMessage(ctx context.Context, msg *Message) (int64, error) {
	const query = `
		INSERT INTO messages (chat_id, user_id, username, first_name, text, message_id, media_type, is_bot_reply, request_id, was_throttled)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
		RETURNING id`

	var id int64
	err := d.pool.QueryRowContext(ctx, query,
		msg.ChatID, msg.UserID, msg.Username, msg.FirstName,
		msg.Text, msg.MessageID, msg.MediaType,
		msg.IsBotReply, msg.RequestID, msg.WasThrottled,
	).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("insert message: %w", err)
	}
	return id, nil
}

// GetRecentMessages returns the last N messages for a chat, ordered oldest to newest.
func (d *DB) GetRecentMessages(ctx context.Context, chatID int64, limit int) ([]Message, error) {
	const query = `
		SELECT id, chat_id, user_id, username, first_name, text, message_id, media_type, is_bot_reply, request_id, was_throttled, created_at
		FROM messages
		WHERE chat_id = $1
		ORDER BY created_at DESC
		LIMIT $2`

	rows, err := d.pool.QueryContext(ctx, query, chatID, limit)
	if err != nil {
		return nil, fmt.Errorf("get recent messages: %w", err)
	}
	defer rows.Close()

	var messages []Message
	for rows.Next() {
		var m Message
		if err := rows.Scan(
			&m.ID, &m.ChatID, &m.UserID, &m.Username, &m.FirstName,
			&m.Text, &m.MessageID, &m.MediaType, &m.IsBotReply,
			&m.RequestID, &m.WasThrottled, &m.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan message: %w", err)
		}
		messages = append(messages, m)
	}

	// Reverse to oldest-first order
	for i, j := 0, len(messages)-1; i < j; i, j = i+1, j-1 {
		messages[i], messages[j] = messages[j], messages[i]
	}

	return messages, nil
}

// ── User Fact Operations ────────────────────────────────────────────────

// InsertUserFact stores a new fact about a user. Duplicates are silently ignored.
func (d *DB) InsertUserFact(ctx context.Context, chatID, userID int64, factText string) (int64, error) {
	const query = `
		INSERT INTO user_facts (chat_id, user_id, fact_text)
		VALUES ($1, $2, $3)
		ON CONFLICT (chat_id, user_id, md5(fact_text)) DO NOTHING
		RETURNING id`

	var id int64
	err := d.pool.QueryRowContext(ctx, query, chatID, userID, factText).Scan(&id)
	if err == sql.ErrNoRows {
		return 0, nil // duplicate — silently ignored
	}
	if err != nil {
		return 0, fmt.Errorf("insert user fact: %w", err)
	}
	return id, nil
}

// GetUserFacts returns all facts stored for a specific user in a chat.
func (d *DB) GetUserFacts(ctx context.Context, chatID, userID int64) ([]UserFact, error) {
	const query = `
		SELECT id, chat_id, user_id, fact_text, created_at, updated_at
		FROM user_facts
		WHERE chat_id = $1 AND user_id = $2
		ORDER BY created_at ASC`

	rows, err := d.pool.QueryContext(ctx, query, chatID, userID)
	if err != nil {
		return nil, fmt.Errorf("get user facts: %w", err)
	}
	defer rows.Close()

	var facts []UserFact
	for rows.Next() {
		var f UserFact
		if err := rows.Scan(&f.ID, &f.ChatID, &f.UserID, &f.FactText, &f.CreatedAt, &f.UpdatedAt); err != nil {
			return nil, fmt.Errorf("scan user fact: %w", err)
		}
		facts = append(facts, f)
	}
	return facts, nil
}

// DeleteUserFact removes a specific fact by ID.
func (d *DB) DeleteUserFact(ctx context.Context, factID int64) error {
	_, err := d.pool.ExecContext(ctx, "DELETE FROM user_facts WHERE id = $1", factID)
	if err != nil {
		return fmt.Errorf("delete user fact: %w", err)
	}
	return nil
}
