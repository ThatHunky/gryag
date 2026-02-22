package tools

import (
	"context"
	"encoding/json"
	"os"
	"testing"

	"github.com/ThatHunky/gryag/backend/internal/config"
)

func TestExecutor_UnknownTool(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	defer os.Unsetenv("GEMINI_API_KEY")
	cfg, _ := config.Load()

	executor := NewExecutor(cfg, nil, nil, nil)
	result := executor.Execute(context.Background(), "nonexistent_tool", json.RawMessage(`{}`))

	if result.Error == "" {
		t.Error("expected error for unknown tool")
	}
}

func TestExecutor_DisabledSandbox(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	os.Setenv("ENABLE_SANDBOX", "false")
	defer func() {
		os.Unsetenv("GEMINI_API_KEY")
		os.Unsetenv("ENABLE_SANDBOX")
	}()
	cfg, _ := config.Load()

	executor := NewExecutor(cfg, nil, nil, nil)
	args := json.RawMessage(`{"code": "print('hello')"}`)
	result := executor.Execute(context.Background(), "run_python_code", args)

	if result.Error != "" {
		t.Errorf("unexpected error: %s", result.Error)
	}
	// Without i18n bundle, should return the key
	if result.Output != "sandbox.disabled" {
		t.Errorf("unexpected output: %s", result.Output)
	}
}

func TestExecutor_DisabledImageGen(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	os.Setenv("ENABLE_IMAGE_GENERATION", "false")
	defer func() {
		os.Unsetenv("GEMINI_API_KEY")
		os.Unsetenv("ENABLE_IMAGE_GENERATION")
	}()
	cfg, _ := config.Load()

	executor := NewExecutor(cfg, nil, nil, nil)
	args := json.RawMessage(`{"prompt": "a cat wearing a hat"}`)
	result := executor.Execute(context.Background(), "generate_image", args)

	if result.Error != "" {
		t.Errorf("unexpected error: %s", result.Error)
	}
	if result.Output != "image.disabled" {
		t.Errorf("unexpected output: %s", result.Output)
	}
}

