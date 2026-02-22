package proactive

import (
	"context"
	"encoding/json"
	"log/slog"
	"math/rand"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/cache"
	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"github.com/ThatHunky/gryag/backend/internal/llm"
	"github.com/ThatHunky/gryag/backend/internal/tools"
	"google.golang.org/genai"
)

const (
	proactiveBlock = "You are initiating without being asked. You may reply to something recent in the chat, or start a new topic. Keep it short and in character. If you have nothing to add, output nothing."
	newsSearchLine = "This turn you MUST conduct a news search: call the search_web tool with a relevant query (e.g. trending or topical), then share something from the results in your reply."
)

// Runner runs one proactive message attempt: pick a chat, call the LLM with proactive instructions, push to queue if reply.
type Runner struct {
	cfg      *config.Config
	db       *db.DB
	llm      *llm.Client
	registry *tools.Registry
	executor *tools.Executor
	cache    *cache.Cache
}

// NewRunner creates a proactive runner.
func NewRunner(cfg *config.Config, database *db.DB, llmClient *llm.Client, reg *tools.Registry, exe *tools.Executor, c *cache.Cache) *Runner {
	return &Runner{cfg: cfg, db: database, llm: llmClient, registry: reg, executor: exe, cache: c}
}

// RunOne picks a recent chat, runs the proactive LLM flow with tools, and pushes a message to the queue if the model replies.
func (r *Runner) RunOne(ctx context.Context) {
	logger := slog.With("component", "proactive")

	chatIDs, err := r.db.GetRecentChatIDs(ctx, 7*24*time.Hour)
	if err != nil {
		logger.Error("get recent chat ids failed", "error", err)
		return
	}
	if len(chatIDs) == 0 {
		return
	}

	chatID := chatIDs[rand.Intn(len(chatIDs))]
	messages, err := r.db.GetRecentMessages(ctx, chatID, r.cfg.ImmediateContextSize)
	if err != nil || len(messages) == 0 {
		return
	}

	// Use last message author as "current" user for context
	var userID int64
	username, firstName := "", ""
	for i := len(messages) - 1; i >= 0; i-- {
		if !messages[i].IsBotReply && messages[i].UserID != nil {
			userID = *messages[i].UserID
			if messages[i].Username != nil {
				username = *messages[i].Username
			}
			if messages[i].FirstName != nil {
				firstName = *messages[i].FirstName
			}
			break
		}
	}

	di, err := llm.NewDynamicInstructions(ctx, r.db, chatID, userID, username, firstName, "[Proactive turn]", r.cfg.ImmediateContextSize)
	if err != nil {
		logger.Error("dynamic instructions failed", "error", err)
		return
	}
	di.ToolsDescription = r.registry.GetToolDescription()

	parts := di.BuildParts()
	proactiveText := proactiveBlock
	if rand.Float32() < 0.30 {
		proactiveText += "\n\n" + newsSearchLine
	}
	// Prepend proactive instruction
	parts = append([]*genai.Part{genai.NewPartFromText(proactiveText)}, parts...)

	contents := []*genai.Content{
		{Role: "user", Parts: parts},
	}
	genaiTools := r.registry.GetTools()

	reply := ""
	for i := 0; i < 5; i++ {
		resp, err := r.llm.GenerateResponse(ctx, contents, genaiTools)
		if err != nil {
			logger.Error("proactive generation failed", "error", err)
			return
		}
		if len(resp.Candidates) == 0 || resp.Candidates[0].Content == nil {
			break
		}
		cand := resp.Candidates[0]
		contents = append(contents, cand.Content)

		hasToolCall := false
		var toolResponses []*genai.Part
		for _, part := range cand.Content.Parts {
			if part.Text != "" {
				reply += part.Text
			} else if part.FunctionCall != nil {
				hasToolCall = true
				args, _ := json.Marshal(part.FunctionCall.Args)
				res := r.executor.Execute(ctx, part.FunctionCall.Name, args)
				payload := map[string]any{"result": res.Output}
				if res.Error != "" {
					payload["error"] = res.Error
				}
				toolResponses = append(toolResponses, genai.NewPartFromFunctionResponse(part.FunctionCall.Name, payload))
			}
		}
		if !hasToolCall {
			break
		}
		reply = ""
		contents = append(contents, &genai.Content{Role: "user", Parts: toolResponses})
	}

	reply = trimSpace(reply)
	if reply == "" {
		return
	}
	if err := r.cache.PushProactive(ctx, cache.ProactiveItem{ChatID: chatID, Reply: reply}); err != nil {
		logger.Error("push proactive failed", "error", err)
		return
	}
	logger.Info("proactive message queued", "chat_id", chatID, "reply_length", len(reply))
}

func trimSpace(s string) string {
	start := 0
	for start < len(s) && (s[start] == ' ' || s[start] == '\n' || s[start] == '\t') {
		start++
	}
	end := len(s)
	for end > start && (s[end-1] == ' ' || s[end-1] == '\n' || s[end-1] == '\t') {
		end--
	}
	return s[start:end]
}
