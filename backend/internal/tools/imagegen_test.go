package tools

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/ThatHunky/gryag/backend/internal/config"
)

func TestAllowedAspectRatios(t *testing.T) {
	valid := []string{"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
	for _, r := range valid {
		if !allowedAspectRatios[r] {
			t.Errorf("expected aspect ratio %q to be allowed", r)
		}
	}
	if allowedAspectRatios["99:99"] {
		t.Error("99:99 should not be in allowed set")
	}
}

func TestGenerateImage_OptionalAspectRatio(t *testing.T) {
	cfg := &config.Config{GeminiAPIKey: ""} // no key -> no API call
	ig := NewImageGenTool(cfg, nil)
	ctx := context.Background()

	// With valid aspect_ratio: parsing succeeds, we get "not configured" (no panic)
	args := json.RawMessage(`{"prompt": "a rabbit", "aspect_ratio": "4:3"}`)
	out, err := ig.GenerateImage(ctx, args)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out != "Image generation is not configured. Set GEMINI_API_KEY." {
		t.Errorf("unexpected output: %s", out)
	}

	// Without aspect_ratio: same behavior
	argsNoRatio := json.RawMessage(`{"prompt": "a rabbit"}`)
	out2, err2 := ig.GenerateImage(ctx, argsNoRatio)
	if err2 != nil {
		t.Fatalf("unexpected error: %v", err2)
	}
	if out2 != "Image generation is not configured. Set GEMINI_API_KEY." {
		t.Errorf("unexpected output: %s", out2)
	}

	// Invalid aspect_ratio is ignored (no error), we still get "not configured"
	argsInvalid := json.RawMessage(`{"prompt": "a rabbit", "aspect_ratio": "99:99"}`)
	out3, err3 := ig.GenerateImage(ctx, argsInvalid)
	if err3 != nil {
		t.Fatalf("unexpected error: %v", err3)
	}
	if out3 != "Image generation is not configured. Set GEMINI_API_KEY." {
		t.Errorf("unexpected output: %s", out3)
	}

	// as_document parses; without API key we still get "not configured"
	argsDoc := json.RawMessage(`{"prompt": "a rabbit", "as_document": true}`)
	out4, err4 := ig.GenerateImage(ctx, argsDoc)
	if err4 != nil {
		t.Fatalf("unexpected error: %v", err4)
	}
	if out4 != "Image generation is not configured. Set GEMINI_API_KEY." {
		t.Errorf("unexpected output: %s", out4)
	}
}

func TestEditImage_ParsesAspectRatio(t *testing.T) {
	cfg := &config.Config{}
	ig := NewImageGenTool(cfg, nil)
	ctx := context.Background()

	// With media_id but no db, we get a message that we need either media_id (with cache) or use_context_image
	args := json.RawMessage(`{"media_id": "abc", "prompt": "add a hat", "aspect_ratio": "16:9"}`)
	out, err := ig.EditImage(ctx, args)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out != "Provide either media_id (from a previous generation) or set use_context_image to true with an image attached to your message." {
		t.Errorf("unexpected output: %s", out)
	}
}
