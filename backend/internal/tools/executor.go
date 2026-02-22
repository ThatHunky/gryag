package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"

	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"github.com/ThatHunky/gryag/backend/internal/i18n"
	"github.com/ThatHunky/gryag/backend/internal/llm"
)

// Executor dispatches tool calls from the LLM to their concrete implementations.
type Executor struct {
	memory    *MemoryTool
	imageGen  *ImageGenTool
	sandbox   *SandboxTool
	db        *db.DB
	config    *config.Config
	i18n      *i18n.Bundle
	lang      string
	llmClient *llm.Client // optional; used for search_web (Gemini Grounding)
}

// NewExecutor creates a new tool executor with all implementations wired up.
// llmClient can be nil; when set, it is used for the search_web tool (Gemini Grounding).
func NewExecutor(cfg *config.Config, database *db.DB, bundle *i18n.Bundle, llmClient *llm.Client) *Executor {
	return &Executor{
		memory:    NewMemoryTool(database, bundle, cfg.DefaultLang),
		imageGen:  NewImageGenTool(cfg, database),
		sandbox:   NewSandboxTool(cfg),
		db:        database,
		config:    cfg,
		i18n:      bundle,
		lang:      cfg.DefaultLang,
		llmClient: llmClient,
	}
}

// ToolResult holds the result of a tool execution.
type ToolResult struct {
	Name   string `json:"name"`
	Output string `json:"output"`
	Error  string `json:"error,omitempty"`
}

// t is a helper for translation within the executor.
func (e *Executor) t(key string, args ...string) string {
	if e.i18n == nil {
		return key
	}
	return e.i18n.T(e.lang, key, args...)
}

// Execute runs a tool by name with the given arguments (JSON).
// Each tool execution is wrapped in an isolated error boundary (Section 15.3).
func (e *Executor) Execute(ctx context.Context, name string, args json.RawMessage) *ToolResult {
	logger := slog.With("tool", name)
	logger.Info("executing tool", "args_length", len(args))

	result := &ToolResult{Name: name}

	// Recover from panics — feature isolation per Section 15.3
	defer func() {
		if r := recover(); r != nil {
			logger.Error("tool panicked", "panic", r)
			result.Error = e.t("tool.internal_error", name)
			result.Output = ""
		}
	}()

	var output string
	var err error

	switch name {
	// Memory tools
	case "recall_memories":
		output, err = e.memory.RecallMemories(ctx, args)
	case "remember_memory":
		output, err = e.memory.RememberMemory(ctx, args)
	case "forget_memory":
		output, err = e.memory.ForgetMemory(ctx, args)

	// Web search (Gemini Grounding)
	case "search_web":
		if !e.config.EnableWebSearch {
			output = e.t("tool.unknown", name)
		} else if e.llmClient == nil {
			output = e.t("tool.search_web_not_configured")
		} else {
			var params struct {
				Query string `json:"query"`
			}
			if jsonErr := json.Unmarshal(args, &params); jsonErr == nil && params.Query != "" {
				output, err = e.llmClient.SearchWithGrounding(ctx, params.Query)
			} else if jsonErr != nil {
				err = jsonErr
			} else {
				output = "Missing or empty query."
			}
		}

	// Message search
	case "search_messages":
		var params struct {
			ChatID int64  `json:"chat_id"`
			Query  string `json:"query"`
			Limit  int    `json:"limit"`
		}
		if jsonErr := json.Unmarshal(args, &params); jsonErr == nil {
			if params.Limit == 0 {
				params.Limit = 10
			}
			results, searchErr := e.db.SearchMessages(ctx, params.ChatID, params.Query, params.Limit)
			if searchErr != nil {
				err = searchErr
			} else if len(results) == 0 {
				output = e.t("search.no_results")
			} else {
				type searchEntry struct {
					Text      string  `json:"text,omitempty"`
					From      string  `json:"from"`
					FileID    string  `json:"file_id,omitempty"`
					MediaType string  `json:"media_type,omitempty"`
					Link      string  `json:"message_link,omitempty"`
					Rank      float64 `json:"relevance"`
				}
				entries := make([]searchEntry, len(results))
				for i, r := range results {
					e := searchEntry{Rank: r.Rank, Link: r.MessageLink}
					if r.Text != nil { e.Text = *r.Text }
					if r.FirstName != nil { e.From = *r.FirstName }
					if r.Username != nil { e.From += " (@" + *r.Username + ")" }
					if r.FileID != nil { e.FileID = *r.FileID }
					if r.MediaType != nil { e.MediaType = *r.MediaType }
					entries[i] = e
				}
				data, _ := json.Marshal(entries)
				output = string(data)
			}
		} else {
			err = jsonErr
		}

	// Calculator — evaluated via sandbox for safety
	case "calculator":
		var params struct {
			Expression string `json:"expression"`
		}
		if jsonErr := json.Unmarshal(args, &params); jsonErr == nil {
			code := fmt.Sprintf("print(eval(%q))", params.Expression)
			codeArgs, _ := json.Marshal(map[string]string{"code": code})
			output, err = e.sandbox.RunPythonCode(ctx, codeArgs)
		} else {
			err = jsonErr
		}

	// Image generation
	case "generate_image":
		if !e.config.EnableImageGeneration {
			output = e.t("image.disabled")
		} else {
			output, err = e.imageGen.GenerateImage(ctx, args)
		}
	case "edit_image":
		if !e.config.EnableImageGeneration {
			output = e.t("image.disabled")
		} else {
			output, err = e.imageGen.EditImage(ctx, args)
		}

	// Code sandbox
	case "run_python_code":
		if !e.config.EnableSandbox {
			output = e.t("sandbox.disabled")
		} else {
			output, err = e.sandbox.RunPythonCode(ctx, codeArgs(args))
		}

	default:
		result.Error = e.t("tool.unknown", name)
		return result
	}

	if err != nil {
		logger.Error("tool execution failed", "error", err)
		result.Error = err.Error()
	} else {
		result.Output = output
	}

	return result
}

// codeArgs is a passthrough for sandbox args.
func codeArgs(args json.RawMessage) json.RawMessage {
	return args
}
