package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/config"
)

// ImageGenTool handles image generation via the Nano Banana Pro API.
type ImageGenTool struct {
	config *config.Config
	client *http.Client
}

// NewImageGenTool creates a new image generation tool.
func NewImageGenTool(cfg *config.Config) *ImageGenTool {
	return &ImageGenTool{
		config: cfg,
		client: &http.Client{Timeout: 120 * time.Second},
	}
}

// GenerateImage creates a new image from a text prompt via the Nano Banana Pro API.
func (ig *ImageGenTool) GenerateImage(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		Prompt string `json:"prompt"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	slog.Info("generating image", "prompt_length", len(params.Prompt))

	if ig.config.NanoBananaAPIKey == "" || ig.config.NanoBananaAPIURL == "" {
		return "Image generation is not configured. Set NANO_BANANA_API_KEY and NANO_BANANA_API_URL.", nil
	}

	// Build the API request
	reqBody, _ := json.Marshal(map[string]any{
		"prompt":  params.Prompt,
		"api_key": ig.config.NanoBananaAPIKey,
		"width":   2560,
		"height":  1440,
	})

	req, err := http.NewRequestWithContext(ctx, "POST", ig.config.NanoBananaAPIURL+"/generate", bytes.NewReader(reqBody))
	if err != nil {
		return "", fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+ig.config.NanoBananaAPIKey)

	resp, err := ig.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("image gen API call failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return fmt.Sprintf("Image generation API returned status %d: %s", resp.StatusCode, string(body)), nil
	}

	// Parse the response to extract the image URL or media_id
	var apiResp struct {
		ImageURL string `json:"image_url"`
		MediaID  string `json:"media_id"`
	}
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return "", fmt.Errorf("parse API response: %w", err)
	}

	slog.Info("image generated", "media_id", apiResp.MediaID)
	return fmt.Sprintf(`{"image_url": %q, "media_id": %q}`, apiResp.ImageURL, apiResp.MediaID), nil
}

// EditImage modifies an existing generated image via the Nano Banana Pro API.
func (ig *ImageGenTool) EditImage(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		MediaID string `json:"media_id"`
		Prompt  string `json:"prompt"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	slog.Info("editing image", "media_id", params.MediaID, "prompt_length", len(params.Prompt))

	if ig.config.NanoBananaAPIKey == "" || ig.config.NanoBananaAPIURL == "" {
		return "Image generation is not configured. Set NANO_BANANA_API_KEY and NANO_BANANA_API_URL.", nil
	}

	// Build the edit request — sends the original media_id and the edit prompt
	reqBody, _ := json.Marshal(map[string]any{
		"media_id": params.MediaID,
		"prompt":   params.Prompt,
		"api_key":  ig.config.NanoBananaAPIKey,
	})

	req, err := http.NewRequestWithContext(ctx, "POST", ig.config.NanoBananaAPIURL+"/edit", bytes.NewReader(reqBody))
	if err != nil {
		return "", fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+ig.config.NanoBananaAPIKey)

	resp, err := ig.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("image edit API call failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode != http.StatusOK {
		return fmt.Sprintf("Image edit API returned status %d: %s", resp.StatusCode, string(body)), nil
	}

	var apiResp struct {
		ImageURL string `json:"image_url"`
		MediaID  string `json:"media_id"`
	}
	if err := json.Unmarshal(body, &apiResp); err != nil {
		return "", fmt.Errorf("parse API response: %w", err)
	}

	slog.Info("image edited", "new_media_id", apiResp.MediaID)
	return fmt.Sprintf(`{"image_url": %q, "media_id": %q}`, apiResp.ImageURL, apiResp.MediaID), nil
}
