package llm

import (
	"testing"

	"github.com/ThatHunky/gryag/backend/internal/db"
)

func TestDynamicInstructions_BuildParts(t *testing.T) {
	di := &DynamicInstructions{
		CurrentTime:    "22:00 Saturday, 22/02/2026",
		ChatID:         -1002604868951,
		ChatName:       "Test Chat",
		CurrentMessage: "Привіт, Гряг!",
		UserID:         392817811,
		Username:       "vsevolod_dobrovolskyi",
		FirstName:      "Vsevolod",
		Summary30Day:   "Lots of chaos happened.",
		Summary7Day:    "More recent chaos.",
	}

	parts := di.BuildParts()

	if len(parts) == 0 {
		t.Fatal("expected parts to be non-empty")
	}

	// Should have at least: time, 30d+7d summaries, current message = 3 parts minimum
	if len(parts) < 3 {
		t.Errorf("expected at least 3 parts, got %d", len(parts))
	}

	// First part should contain the current time
	firstText := parts[0].Text
	if firstText == "" {
		t.Error("expected first part to contain time text")
	}
}

func TestDynamicInstructions_BuildParts_WithMessages(t *testing.T) {
	username := "testuser"
	firstName := "Test"
	text := "Hello there"

	di := &DynamicInstructions{
		CurrentTime:    "10:00 Monday, 24/02/2026",
		ChatID:         123,
		CurrentMessage: "New message",
		UserID:         456,
		Username:       "sender",
		FirstName:      "Sender",
		RecentMessages: []db.Message{
			{
				ChatID:    123,
				Username:  &username,
				FirstName: &firstName,
				Text:      &text,
			},
		},
	}

	parts := di.BuildParts()

	// Should have: time + chat context + current message = 3 parts min
	if len(parts) < 3 {
		t.Errorf("expected at least 3 parts, got %d", len(parts))
	}
}

func TestDynamicInstructions_BuildParts_WithFacts(t *testing.T) {
	di := &DynamicInstructions{
		CurrentTime:    "10:00 Monday, 24/02/2026",
		ChatID:         123,
		CurrentMessage: "Test",
		UserID:         456,
		FirstName:      "Test",
		UserFacts: []db.UserFact{
			{ChatID: 123, UserID: 456, FactText: "Likes cats"},
			{ChatID: 123, UserID: 456, FactText: "Lives in Kyiv"},
		},
	}

	parts := di.BuildParts()

	// Should have: time + user facts + current message = 3 parts min
	if len(parts) < 3 {
		t.Errorf("expected at least 3 parts, got %d", len(parts))
	}
}
