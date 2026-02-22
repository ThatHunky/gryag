package tools

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/ThatHunky/gryag/backend/internal/config"
	"google.golang.org/genai"
)

// ImageGenTool handles image generation via Gemini 3 Pro Image.
type ImageGenTool struct {
	config *config.Config
}

// NewImageGenTool creates a new image generation tool.
func NewImageGenTool(cfg *config.Config) *ImageGenTool {
	return &ImageGenTool{
		config: cfg,
	}
}

// GenerateImage creates a new image from a text prompt via Gemini 3 Pro Image.
func (ig *ImageGenTool) GenerateImage(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		Prompt string `json:"prompt"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	slog.Info("generating image", "prompt_length", len(params.Prompt))

	if ig.config.GeminiAPIKey == "" {
		return "Image generation is not configured. Set GEMINI_API_KEY.", nil
	}

	client, err := genai.NewClient(ctx, &genai.ClientConfig{
		APIKey:  ig.config.GeminiAPIKey,
		Backend: genai.BackendGeminiAPI,
	})
	if err != nil {
		return "", fmt.Errorf("genai client: %w", err)
	}

	config := &genai.GenerateContentConfig{
		// ResponseModalities: []string{"IMAGE"} is deprecated in favor of specific model defaults or ImageConfig
	}

	resp, err := client.Models.GenerateContent(ctx, "gemini-3-pro-image-preview", []*genai.Content{
		{
			Role:  "user",
			Parts: []*genai.Part{genai.NewPartFromText(params.Prompt)},
		},
	}, config)

	if err != nil {
		return "", fmt.Errorf("image gen API call failed: %w", err)
	}

	if len(resp.Candidates) == 0 || resp.Candidates[0].Content == nil {
		return "API returned no candidates", nil
	}

	// Find the image data
	for _, part := range resp.Candidates[0].Content.Parts {
		if part.InlineData != nil {
			// We found the image! Base64 encode it and return it in a special JSON format.
			b64 := base64.StdEncoding.EncodeToString(part.InlineData.Data)
			return fmt.Sprintf(`{"media_base64": "%s", "media_type": "photo"}`, b64), nil
		}
	}

	return "API returned candidates but no inline image data", nil
}

// EditImage is disabled for now, but stubbed.
func (ig *ImageGenTool) EditImage(ctx context.Context, args json.RawMessage) (string, error) {
	return "Image editing is currently not supported by this API.", nil
}
