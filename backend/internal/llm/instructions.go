package llm

import (
	"context"
	"fmt"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/db"
	"google.golang.org/genai"
)

// DynamicInstructions assembles the full prompt per Section 8 of the architecture.
type DynamicInstructions struct {
	// Section 8.2: Current time and chat info
	CurrentTime string
	ChatName    string
	ChatID      int64

	// Section 8.3: Tools block (built separately via registry)
	ToolsDescription string

	// Section 8.4: Multi-tiered summaries
	Summary30Day string
	Summary7Day  string

	// Section 8.4 + 8.6: Immediate chat context (last N messages)
	RecentMessages []db.Message

	// Section 8.5: Current user context
	UserFacts []db.UserFact
	UserID    int64
	Username  string
	FirstName string

	// Section 8.6: Multi-media buffer (up to 10 media items)
	MediaParts []*genai.Part

	// Section 8.7: Current message
	CurrentMessage string
}

// NewDynamicInstructions creates a DynamicInstructions from the database context.
func NewDynamicInstructions(
	ctx context.Context,
	database *db.DB,
	chatID int64,
	userID int64,
	username, firstName, text string,
	contextSize int,
) (*DynamicInstructions, error) {
	di := &DynamicInstructions{
		CurrentTime:    time.Now().Format("15:04 Monday, 02/01/2006"),
		ChatID:         chatID,
		UserID:         userID,
		Username:       username,
		FirstName:      firstName,
		CurrentMessage: text,
	}

	// Load recent messages for immediate context
	messages, err := database.GetRecentMessages(ctx, chatID, contextSize)
	if err != nil {
		return nil, fmt.Errorf("get recent messages: %w", err)
	}
	di.RecentMessages = messages

	// Load user facts for current user context
	facts, err := database.GetUserFacts(ctx, chatID, userID)
	if err != nil {
		return nil, fmt.Errorf("get user facts: %w", err)
	}
	di.UserFacts = facts

	return di, nil
}

// BuildParts assembles the Dynamic Instructions into genai.Part entries
// following the strict ordering from Section 8.
func (di *DynamicInstructions) BuildParts() []*genai.Part {
	var parts []*genai.Part

	// 1. Current Time & Chat Info (Section 8.2)
	timeBlock := fmt.Sprintf("# Current Time\n%s\n\n# Chat Info\nChat ID: %d",
		di.CurrentTime, di.ChatID)
	if di.ChatName != "" {
		timeBlock += fmt.Sprintf("\nChat Name: %s", di.ChatName)
	}
	parts = append(parts, genai.NewPartFromText(timeBlock))

	// 2. Tools Block (Section 8.3) — injected as descriptive text
	if di.ToolsDescription != "" {
		parts = append(parts, genai.NewPartFromText("# Available Tools\n"+di.ToolsDescription))
	}

	// 3. Context Summaries (Section 8.4)
	contextBlock := ""
	if di.Summary30Day != "" {
		contextBlock += "# 30-Day Summary\n" + di.Summary30Day + "\n\n"
	}
	if di.Summary7Day != "" {
		contextBlock += "# 7-Day Summary\n" + di.Summary7Day + "\n\n"
	}
	if contextBlock != "" {
		parts = append(parts, genai.NewPartFromText(contextBlock))
	}

	// 4. Immediate Chat Context (Section 8.4 bottom)
	if len(di.RecentMessages) > 0 {
		chatLog := "# Immediate Chat Context\n"
		for _, msg := range di.RecentMessages {
			name := "Unknown"
			if msg.FirstName != nil {
				name = *msg.FirstName
			}
			if msg.Username != nil {
				name += " (@" + *msg.Username + ")"
			}

			text := ""
			if msg.Text != nil {
				text = *msg.Text
			}

			prefix := ""
			if msg.IsBotReply {
				prefix = "[BOT] "
			}
			if msg.WasThrottled {
				prefix = "[THROTTLED] "
			}

			chatLog += fmt.Sprintf("%s%s: %s\n", prefix, name, text)
		}
		parts = append(parts, genai.NewPartFromText(chatLog))
	}

	// 5. Current User Context (Section 8.5)
	if len(di.UserFacts) > 0 {
		factsBlock := fmt.Sprintf("# Current User Context (user_id: %d)\n", di.UserID)
		for _, f := range di.UserFacts {
			factsBlock += fmt.Sprintf("- %s\n", f.FactText)
		}
		parts = append(parts, genai.NewPartFromText(factsBlock))
	}

	// 6. Multi-Media Buffer (Section 8.6)
	// Up to 10 media parts injected directly as genai.Part entries
	parts = append(parts, di.MediaParts...)

	// 7. Current Message (Section 8.7)
	msgBlock := fmt.Sprintf("# Current Message\nFrom: %s", di.FirstName)
	if di.Username != "" {
		msgBlock += fmt.Sprintf(" (@%s)", di.Username)
	}
	msgBlock += fmt.Sprintf(" [user_id: %d]\nMessage: %s", di.UserID, di.CurrentMessage)
	parts = append(parts, genai.NewPartFromText(msgBlock))

	return parts
}
