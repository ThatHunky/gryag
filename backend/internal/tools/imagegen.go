package tools

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"

	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"google.golang.org/genai"
)

// ImageGenTool handles image generation and editing via Gemini 3 Pro Image.
type ImageGenTool struct {
	config *config.Config
	db     *db.DB
}

// NewImageGenTool creates a new image generation tool.
func NewImageGenTool(cfg *config.Config, database *db.DB) *ImageGenTool {
	return &ImageGenTool{
		config: cfg,
		db:     database,
	}
}

// allowedAspectRatios are the values supported by the Gemini image API (including 4:5, 5:4 per flexible ratios).
var allowedAspectRatios = map[string]bool{
	"1:1": true, "2:3": true, "3:2": true, "3:4": true,
	"4:3": true, "4:5": true, "5:4": true, "9:16": true, "16:9": true, "21:9": true,
}

// GenerateImage creates a new image from a text prompt via Gemini 3 Pro Image.
func (ig *ImageGenTool) GenerateImage(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		Prompt      string `json:"prompt"`
		AspectRatio string `json:"aspect_ratio"`
		AsDocument  bool   `json:"as_document"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	mediaType := "photo"
	if params.AsDocument {
		mediaType = "document"
	}
	slog.Info("generating image", "prompt_length", len(params.Prompt), "aspect_ratio", params.AspectRatio, "as_document", params.AsDocument)

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

	genConfig := &genai.GenerateContentConfig{}
	if params.AspectRatio != "" {
		if allowedAspectRatios[params.AspectRatio] {
			genConfig.ImageConfig = &genai.ImageConfig{AspectRatio: params.AspectRatio}
		} else {
			slog.Warn("ignoring unsupported aspect_ratio", "aspect_ratio", params.AspectRatio)
		}
	}

	resp, err := client.Models.GenerateContent(ctx, "gemini-3-pro-image-preview", []*genai.Content{
		{
			Role:  "user",
			Parts: []*genai.Part{genai.NewPartFromText(params.Prompt)},
		},
	}, genConfig)

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
			return fmt.Sprintf(`{"media_base64": "%s", "media_type": "%s"}`, b64, mediaType), nil
		}
	}

	return "API returned candidates but no inline image data", nil
}

// EditImage edits an image: from context (use_context_image) or from media_cache (media_id).
func (ig *ImageGenTool) EditImage(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		MediaID          string `json:"media_id"`
		UseContextImage  bool   `json:"use_context_image"`
		Prompt           string `json:"prompt"`
		AspectRatio      string `json:"aspect_ratio"`
		AsDocument       bool   `json:"as_document"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	var imageData []byte
	if params.UseContextImage {
		v := ctx.Value(RequestMediaBase64Key)
		if v == nil {
			return "No image attached to this message. Attach a photo and ask again.", nil
		}
		b64, ok := v.(string)
		if !ok || b64 == "" {
			return "No image attached to this message. Attach a photo and ask again.", nil
		}
		var err error
		imageData, err = base64.StdEncoding.DecodeString(b64)
		if err != nil {
			return "", fmt.Errorf("decode context image: %w", err)
		}
	} else if params.MediaID != "" && ig.db != nil {
		entry, err := ig.db.GetMediaCacheByID(ctx, params.MediaID)
		if err != nil {
			return "", fmt.Errorf("get media cache: %w", err)
		}
		if entry == nil {
			return "That image is no longer available for editing (expired or invalid media_id).", nil
		}
		imageData, err = os.ReadFile(entry.FilePath)
		if err != nil {
			return "", fmt.Errorf("read cached image: %w", err)
		}
	} else {
		return "Provide either media_id (from a previous generation) or set use_context_image to true with an image attached to your message.", nil
	}

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

	genConfig := &genai.GenerateContentConfig{}
	if params.AspectRatio != "" && allowedAspectRatios[params.AspectRatio] {
		genConfig.ImageConfig = &genai.ImageConfig{AspectRatio: params.AspectRatio}
	}

	// Edit: send image + text prompt to the same model
	parts := []*genai.Part{
		genai.NewPartFromBytes(imageData, "image/png"),
		genai.NewPartFromText(params.Prompt),
	}
	resp, err := client.Models.GenerateContent(ctx, "gemini-3-pro-image-preview", []*genai.Content{
		{Role: "user", Parts: parts},
	}, genConfig)
	if err != nil {
		return "", fmt.Errorf("image edit API call failed: %w", err)
	}

	if len(resp.Candidates) == 0 || resp.Candidates[0].Content == nil {
		return "API returned no candidates", nil
	}

	mediaType := "photo"
	if params.AsDocument {
		mediaType = "document"
	}
	for _, part := range resp.Candidates[0].Content.Parts {
		if part.InlineData != nil {
			b64 := base64.StdEncoding.EncodeToString(part.InlineData.Data)
			return fmt.Sprintf(`{"media_base64": "%s", "media_type": "%s"}`, b64, mediaType), nil
		}
	}
	return "API returned no image data", nil
}
