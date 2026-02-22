package db

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
)

// SearchResult holds a message match from full-text search.
type SearchResult struct {
	ID        int64
	ChatID    int64
	UserID    *int64
	Username  *string
	FirstName *string
	Text      *string
	FileID    *string
	MessageID *int64
	MediaType *string
	IsBotReply bool
	Rank      float64
	MessageLink string // Composed Telegram deep link
}

// SearchMessages performs full-text search on the messages table for a given chat.
// Returns results ranked by relevance with Telegram deep links composed.
func (d *DB) SearchMessages(ctx context.Context, chatID int64, query string, limit int) ([]SearchResult, error) {
	if limit <= 0 {
		limit = 10
	}
	if limit > 50 {
		limit = 50
	}

	// Build the tsquery — split on spaces, join with & for AND matching
	words := strings.Fields(query)
	if len(words) == 0 {
		return nil, nil
	}

	// Use prefix matching (:*) for partial word matches
	tsTerms := make([]string, len(words))
	for i, w := range words {
		tsTerms[i] = w + ":*"
	}
	tsQuery := strings.Join(tsTerms, " & ")

	const sqlQuery = `
		SELECT id, chat_id, user_id, username, first_name, text, file_id, message_id, media_type, is_bot_reply,
		       ts_rank(search_vector, to_tsquery('simple', $1)) AS rank
		FROM messages
		WHERE chat_id = $2 AND search_vector @@ to_tsquery('simple', $1)
		ORDER BY rank DESC, created_at DESC
		LIMIT $3`

	rows, err := d.pool.QueryContext(ctx, sqlQuery, tsQuery, chatID, limit)
	if err != nil {
		return nil, fmt.Errorf("search messages: %w", err)
	}
	defer rows.Close()

	var results []SearchResult
	for rows.Next() {
		var r SearchResult
		if err := rows.Scan(
			&r.ID, &r.ChatID, &r.UserID, &r.Username, &r.FirstName,
			&r.Text, &r.FileID, &r.MessageID, &r.MediaType, &r.IsBotReply, &r.Rank,
		); err != nil {
			return nil, fmt.Errorf("scan search result: %w", err)
		}
		r.MessageLink = ComposeMessageLink(r.ChatID, r.MessageID)
		results = append(results, r)
	}

	slog.Info("message search", "chat_id", chatID, "query", query, "results", len(results))
	return results, nil
}

// ComposeMessageLink creates a Telegram deep link to a specific message.
// For private groups (chat_id starts with -100), the link is:
//
//	https://t.me/c/{chat_id_without_-100_prefix}/{message_id}
//
// For other chats, we can't compose a reliable link, so we return empty.
func ComposeMessageLink(chatID int64, messageID *int64) string {
	if messageID == nil || *messageID == 0 {
		return ""
	}

	// Private supergroups/channels: chat_id is -100XXXXXXXXXX
	// The deep link uses the numeric part without the -100 prefix
	if chatID < -1000000000000 {
		// Strip the -100 prefix: -1001234567890 → 1234567890
		innerID := chatID * -1 - 1000000000000
		return fmt.Sprintf("https://t.me/c/%d/%d", innerID, *messageID)
	}

	// For basic groups (negative, but not -100 prefix), links aren't supported
	// For private chats (positive), links aren't supported
	return ""
}
