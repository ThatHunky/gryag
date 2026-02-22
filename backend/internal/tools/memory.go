package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/ThatHunky/gryag/backend/internal/db"
	"github.com/ThatHunky/gryag/backend/internal/i18n"
)

// MemoryTool handles recall_memories, remember_memory, forget_memory operations.
type MemoryTool struct {
	db   *db.DB
	i18n *i18n.Bundle
	lang string
}

// NewMemoryTool creates a new memory tool backed by PostgreSQL.
func NewMemoryTool(database *db.DB, bundle *i18n.Bundle, lang string) *MemoryTool {
	return &MemoryTool{db: database, i18n: bundle, lang: lang}
}

// t is a shorthand for translation.
func (m *MemoryTool) t(key string, args ...string) string {
	if m.i18n == nil {
		return key
	}
	return m.i18n.T(m.lang, key, args...)
}

// RecallMemories retrieves all stored facts for a user in a chat.
func (m *MemoryTool) RecallMemories(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		UserID int64 `json:"user_id"`
		ChatID int64 `json:"chat_id"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	facts, err := m.db.GetUserFacts(ctx, params.ChatID, params.UserID)
	if err != nil {
		return "", fmt.Errorf("get user facts: %w", err)
	}

	if len(facts) == 0 {
		return m.t("memory.none"), nil
	}

	type memoryEntry struct {
		ID   int64  `json:"memory_id"`
		Text string `json:"memory_text"`
	}

	entries := make([]memoryEntry, len(facts))
	for i, f := range facts {
		entries[i] = memoryEntry{ID: f.ID, Text: f.FactText}
	}

	result, _ := json.Marshal(entries)
	slog.Info("recalled memories", "user_id", params.UserID, "count", len(facts))
	return string(result), nil
}

// RememberMemory stores a new fact about a user.
func (m *MemoryTool) RememberMemory(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		UserID     int64  `json:"user_id"`
		ChatID     int64  `json:"chat_id"`
		MemoryText string `json:"memory_text"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	id, err := m.db.InsertUserFact(ctx, params.ChatID, params.UserID, params.MemoryText)
	if err != nil {
		return "", fmt.Errorf("insert fact: %w", err)
	}

	if id == 0 {
		return m.t("memory.duplicate"), nil
	}

	slog.Info("stored memory", "user_id", params.UserID, "fact_id", id)
	return m.t("memory.stored", fmt.Sprintf("%d", id)), nil
}

// ForgetMemory deletes a specific memory by ID.
func (m *MemoryTool) ForgetMemory(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		MemoryID int64 `json:"memory_id"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	if err := m.db.DeleteUserFact(ctx, params.MemoryID); err != nil {
		return "", fmt.Errorf("delete fact: %w", err)
	}

	slog.Info("forgot memory", "memory_id", params.MemoryID)
	return m.t("memory.forgotten", fmt.Sprintf("%d", params.MemoryID)), nil
}
