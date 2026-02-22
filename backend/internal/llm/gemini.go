package llm

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"strings"

	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"google.golang.org/genai"
)

const maxSummaryInputChars = 100_000

// Client wraps the Google GenAI SDK client for Gemini interactions.
type Client struct {
	genai  *genai.Client
	config *config.Config
	persona string
}

// NewClient creates a new Gemini LLM client.
func NewClient(cfg *config.Config) (*Client, error) {
	ctx := context.Background()
	client, err := genai.NewClient(ctx, &genai.ClientConfig{
		APIKey:  cfg.GeminiAPIKey,
		Backend: genai.BackendGeminiAPI,
	})
	if err != nil {
		return nil, fmt.Errorf("genai client: %w", err)
	}

	// Load the hot-swappable persona file (Section 13)
	persona, err := os.ReadFile(cfg.PersonaFile)
	if err != nil {
		return nil, fmt.Errorf("read persona file %s: %w", cfg.PersonaFile, err)
	}

	slog.Info("gemini client initialized",
		"model", cfg.GeminiModel,
		"persona_file", cfg.PersonaFile,
		"persona_length", len(persona),
	)

	return &Client{
		genai:   client,
		config:  cfg,
		persona: string(persona),
	}, nil
}

// GenerateResponse sends a conversation history to Gemini and returns the full response.
func (c *Client) GenerateResponse(ctx context.Context, contents []*genai.Content, tools []*genai.Tool) (*genai.GenerateContentResponse, error) {
	logger := slog.With("model", c.config.GeminiModel)

	config := &genai.GenerateContentConfig{
		// Section 14.1: SystemInstruction is the persona — separated from the conversation array
		SystemInstruction: &genai.Content{
			Parts: []*genai.Part{genai.NewPartFromText(c.persona)},
		},
		Temperature:      genai.Ptr(float32(c.config.GeminiTemperature)),
		Tools:            tools,
	}

	if c.config.GeminiThinkingBudget > 0 {
		config.ThinkingConfig = &genai.ThinkingConfig{
			ThinkingBudget: genai.Ptr(int32(c.config.GeminiThinkingBudget)),
		}
	}

	resp, err := c.genai.Models.GenerateContent(ctx, c.config.GeminiModel, contents, config)
	if err != nil {
		return nil, fmt.Errorf("generate content: %w", err)
	}

	logger.Info("generation complete")
	return resp, nil
}

// RouteIntent uses the model at low temperature to decide what tool(s) to call.
// Returns structured JSON per Section 14.2.
func (c *Client) RouteIntent(ctx context.Context, message string, tools []*genai.Tool) (*genai.GenerateContentResponse, error) {
	config := &genai.GenerateContentConfig{
		SystemInstruction: &genai.Content{
			Parts: []*genai.Part{genai.NewPartFromText(c.persona)},
		},
		// Section 14.3: Low temperature for deterministic routing
		Temperature: genai.Ptr(float32(c.config.GeminiRoutingTemperature)),
		Tools:       tools,
		// Section 14.2: Strict structured output enforcement
		ResponseMIMEType: "application/json",
	}

	resp, err := c.genai.Models.GenerateContent(ctx, c.config.GeminiModel, []*genai.Content{
		{
			Role:  "user",
			Parts: []*genai.Part{genai.NewPartFromText(message)},
		},
	}, config)
	if err != nil {
		return nil, fmt.Errorf("route intent: %w", err)
	}

	return resp, nil
}

// SummarizeChat produces a short factual summary of a chat log for the given window (e.g. "7-day", "30-day").
// Messages are formatted like the immediate context block; input is truncated to maxSummaryInputChars.
func (c *Client) SummarizeChat(ctx context.Context, messages []db.Message, windowLabel string) (string, error) {
	if len(messages) == 0 {
		return "", nil
	}
	var b strings.Builder
	for _, msg := range messages {
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
		b.WriteString(fmt.Sprintf("%s%s: %s\n", prefix, name, text))
	}
	chatLog := b.String()
	if len(chatLog) > maxSummaryInputChars {
		chatLog = chatLog[len(chatLog)-maxSummaryInputChars:]
	}
	systemInstruction := "You are a summarization assistant. Summarize the following chat log concisely and factually. Preserve key topics, decisions, and context. Use the same language as the chat or English. Output only the summary, no preamble."
	userContent := "Summarize this " + windowLabel + " conversation:\n\n" + chatLog
	config := &genai.GenerateContentConfig{
		SystemInstruction: &genai.Content{
			Parts: []*genai.Part{genai.NewPartFromText(systemInstruction)},
		},
		Temperature: genai.Ptr(float32(0.2)),
	}
	contents := []*genai.Content{
		{Role: "user", Parts: []*genai.Part{genai.NewPartFromText(userContent)}},
	}
	resp, err := c.genai.Models.GenerateContent(ctx, c.config.GeminiModel, contents, config)
	if err != nil {
		return "", fmt.Errorf("summarize chat: %w", err)
	}
	return extractText(resp), nil
}

// SearchWithGrounding runs a single Gemini request with Google Search grounding and returns
// the model's grounded response text. Used by the search_web tool.
func (c *Client) SearchWithGrounding(ctx context.Context, query string) (string, error) {
	config := &genai.GenerateContentConfig{
		Tools: []*genai.Tool{{GoogleSearch: &genai.GoogleSearch{}}},
		// No system instruction needed for a simple search; the model answers from search results.
	}
	contents := []*genai.Content{
		{Role: "user", Parts: []*genai.Part{genai.NewPartFromText(query)}},
	}
	resp, err := c.genai.Models.GenerateContent(ctx, c.config.GeminiModel, contents, config)
	if err != nil {
		return "", fmt.Errorf("grounding request: %w", err)
	}
	return extractText(resp), nil
}

// extractText pulls the text content from a Gemini response.
func extractText(resp *genai.GenerateContentResponse) string {
	if resp == nil || len(resp.Candidates) == 0 {
		return ""
	}
	candidate := resp.Candidates[0]
	if candidate.Content == nil || len(candidate.Content.Parts) == 0 {
		return ""
	}

	var result string
	for _, part := range candidate.Content.Parts {
		if part.Text != "" {
			result += part.Text
		}
	}
	return result
}
