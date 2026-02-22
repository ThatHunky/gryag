package tools

import (
	"os"
	"testing"

	"github.com/ThatHunky/gryag/backend/internal/config"
)

func loadTestConfig(t *testing.T) *config.Config {
	t.Helper()
	os.Setenv("GEMINI_API_KEY", "test-key")
	t.Cleanup(func() { os.Unsetenv("GEMINI_API_KEY") })
	cfg, err := config.Load()
	if err != nil {
		t.Fatalf("config load: %v", err)
	}
	return cfg
}

func TestRegistry_AllToolsRegistered(t *testing.T) {
	cfg := loadTestConfig(t)
	r := NewRegistry(cfg)

	// With defaults (sandbox + image gen enabled), we expect:
	// recall_memories, remember_memory, forget_memory, calculator,
	// weather, currency, search_messages, generate_image, edit_image, run_python_code = 10
	expected := 10
	if r.Count() != expected {
		t.Errorf("expected %d tools, got %d", expected, r.Count())
		t.Logf("registered tools: %v", r.GetToolNames())
	}
}

func TestRegistry_FeatureToggles(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	os.Setenv("ENABLE_SANDBOX", "false")
	os.Setenv("ENABLE_IMAGE_GENERATION", "false")
	t.Cleanup(func() {
		os.Unsetenv("GEMINI_API_KEY")
		os.Unsetenv("ENABLE_SANDBOX")
		os.Unsetenv("ENABLE_IMAGE_GENERATION")
	})

	cfg, _ := config.Load()
	r := NewRegistry(cfg)

	// With sandbox + image gen disabled, we expect:
	// recall_memories, remember_memory, forget_memory, calculator,
	// weather, currency, search_messages = 7
	expected := 7
	if r.Count() != expected {
		t.Errorf("expected %d tools, got %d", expected, r.Count())
		t.Logf("registered tools: %v", r.GetToolNames())
	}

	if r.HasTool("run_python_code") {
		t.Error("run_python_code should not be registered when sandbox is disabled")
	}
	if r.HasTool("generate_image") {
		t.Error("generate_image should not be registered when image gen is disabled")
	}
}

func TestRegistry_GetTools_IncludesGoogleSearch(t *testing.T) {
	cfg := loadTestConfig(t)
	r := NewRegistry(cfg)
	tools := r.GetTools()

	// Should have 2 entries: one with FunctionDeclarations, one with GoogleSearch
	if len(tools) != 2 {
		t.Fatalf("expected 2 tool groups, got %d", len(tools))
	}

	hasSearch := false
	for _, tool := range tools {
		if tool.GoogleSearch != nil {
			hasSearch = true
		}
	}
	if !hasSearch {
		t.Error("expected GoogleSearch to be present in tools")
	}
}

func TestRegistry_GetTools_NoSearchWhenDisabled(t *testing.T) {
	os.Setenv("GEMINI_API_KEY", "test-key")
	os.Setenv("ENABLE_WEB_SEARCH", "false")
	t.Cleanup(func() {
		os.Unsetenv("GEMINI_API_KEY")
		os.Unsetenv("ENABLE_WEB_SEARCH")
	})

	cfg, _ := config.Load()
	r := NewRegistry(cfg)
	tools := r.GetTools()

	for _, tool := range tools {
		if tool.GoogleSearch != nil {
			t.Error("GoogleSearch should not be present when web search is disabled")
		}
	}
}

func TestRegistry_GetToolDescription(t *testing.T) {
	cfg := loadTestConfig(t)
	r := NewRegistry(cfg)
	desc := r.GetToolDescription()

	if desc == "" {
		t.Error("expected non-empty tool description")
	}

	// Should contain at least one tool name
	if !r.HasTool("recall_memories") {
		t.Error("expected recall_memories to be registered")
	}
}
