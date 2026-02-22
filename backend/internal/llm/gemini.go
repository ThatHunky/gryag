package llm

import (
	"context"
	"fmt"
	"log/slog"
	"os"

	"github.com/ThatHunky/gryag/backend/internal/config"
	"google.golang.org/genai"
)

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

// GenerateResponse sends a fully assembled Dynamic Instructions prompt to Gemini
// and returns the model's text response.
func (c *Client) GenerateResponse(ctx context.Context, instructions *DynamicInstructions, tools []*genai.Tool) (string, error) {
	logger := slog.With("model", c.config.GeminiModel)

	// Build the content parts from the Dynamic Instructions
	parts := instructions.BuildParts()

	config := &genai.GenerateContentConfig{
		// Section 14.1: SystemInstruction is the persona — separated from the conversation array
		SystemInstruction: &genai.Content{
			Parts: []*genai.Part{genai.NewPartFromText(c.persona)},
		},
		Temperature:      genai.Ptr(float32(c.config.GeminiTemperature)),
		Tools:            tools,
	}

	resp, err := c.genai.Models.GenerateContent(ctx, c.config.GeminiModel, []*genai.Content{
		{
			Role:  "user",
			Parts: parts,
		},
	}, config)
	if err != nil {
		return "", fmt.Errorf("generate content: %w", err)
	}

	// Extract the text response
	text := extractText(resp)
	logger.Info("generation complete", "response_length", len(text))
	return text, nil
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
