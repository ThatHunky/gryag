package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"

	"github.com/ThatHunky/gryag/backend/internal/cache"
	"github.com/ThatHunky/gryag/backend/internal/config"
	"github.com/ThatHunky/gryag/backend/internal/db"
	"github.com/ThatHunky/gryag/backend/internal/llm"
	"github.com/ThatHunky/gryag/backend/internal/tools"
	"google.golang.org/genai"
)

// ProcessRequest holds the incoming message payload from the Python frontend.
type ProcessRequest struct {
	ChatID    int64  `json:"chat_id"`
	UserID    *int64 `json:"user_id"`
	Username  string `json:"username"`
	FirstName string `json:"first_name"`
	Text      string `json:"text"`
	MessageID int64  `json:"message_id"`
	Date      string `json:"date"`
	FileID    string `json:"file_id"`
	MediaType string `json:"media_type"`
}

type ProcessResponse struct {
	Reply       string `json:"reply"`
	RequestID   string `json:"request_id"`
	MediaURL    string `json:"media_url,omitempty"`
	MediaType   string `json:"media_type,omitempty"`
	MediaBase64 string `json:"media_base64,omitempty"`
}

// Handler wires all subsystems together for request processing.
type Handler struct {
	db       *db.DB
	cache    *cache.Cache
	llm      *llm.Client
	registry *tools.Registry
	executor *tools.Executor
	config   *config.Config
}

// New creates a new request handler with all dependencies.
func New(cfg *config.Config, database *db.DB, c *cache.Cache, llmClient *llm.Client, reg *tools.Registry, exe *tools.Executor) *Handler {
	return &Handler{
		db:       database,
		cache:    c,
		llm:      llmClient,
		registry: reg,
		executor: exe,
		config:   cfg,
	}
}

// Process handles the /api/v1/process endpoint — the main entry point for messages.
func (h *Handler) Process(w http.ResponseWriter, r *http.Request) {
	requestID := r.Header.Get("X-Request-ID")
	logger := slog.With("request_id", requestID)

	var req ProcessRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		logger.Warn("invalid request payload", "error", err)
		http.Error(w, `{"error":"invalid payload"}`, http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	logger.Info("processing message",
		"chat_id", req.ChatID,
		"user_id", req.UserID,
		"text_length", len(req.Text),
	)

	ctx := r.Context()

	// 1. Log the incoming message to PostgreSQL (even if later throttled at tool level)
	userID := int64(0)
	if req.UserID != nil {
		userID = *req.UserID
	}
	msgRecord := &db.Message{
		ChatID:    req.ChatID,
		UserID:    req.UserID,
		Username:  strPtr(req.Username),
		FirstName: strPtr(req.FirstName),
		Text:      strPtr(req.Text),
		MessageID: &req.MessageID,
		RequestID: &requestID,
		FileID:    strPtr(req.FileID),
		MediaType: strPtr(req.MediaType),
	}
	if _, err := h.db.InsertMessage(ctx, msgRecord); err != nil {
		logger.Error("failed to store incoming message", "error", err)
	}

	// 2. Build Dynamic Instructions from DB context
	di, err := llm.NewDynamicInstructions(ctx, h.db, req.ChatID, userID, req.Username, req.FirstName, req.Text, h.config.ImmediateContextSize)
	if err != nil {
		logger.Error("failed to build dynamic instructions", "error", err)
		respondJSON(w, &ProcessResponse{Reply: "Internal error building context.", RequestID: requestID})
		return
	}
	di.ToolsDescription = h.registry.GetToolDescription()

	// 3. Get the registered tools for the API call
	genaiTools := h.registry.GetTools()

	// 4. Initial conversation history payload
	contents := []*genai.Content{
		{
			Role:  "user",
			Parts: di.BuildParts(),
		},
	}

	reply := ""
	mediaBase64 := ""
	mediaType := ""

	// 5. Tool execution loop (max 5 iterations to prevent infinite loops)
	for i := 0; i < 5; i++ {
		resp, err := h.llm.GenerateResponse(ctx, contents, genaiTools)
		if err != nil {
			logger.Error("gemini generation failed", "error", err)
			respondJSON(w, &ProcessResponse{Reply: "Error generating response.", RequestID: requestID})
			return
		}

		if len(resp.Candidates) == 0 || resp.Candidates[0].Content == nil {
			break
		}
		cand := resp.Candidates[0]

		// Ensure we append the model's exact response to the history
		contents = append(contents, cand.Content)

		hasToolCall := false
		var toolResponses []*genai.Part

		for _, part := range cand.Content.Parts {
			if part.Text != "" {
				reply += part.Text
			} else if part.FunctionCall != nil {
				hasToolCall = true
				res := h.HandleToolCall(ctx, part.FunctionCall)

				returnToModel := res.Output

				// Intercept image output to avoid context bloat!
				if part.FunctionCall.Name == "generate_image" {
					var raw struct {
						MediaBase64 string `json:"media_base64"`
					}
					if err := json.Unmarshal([]byte(res.Output), &raw); err == nil && raw.MediaBase64 != "" {
						mediaBase64 = raw.MediaBase64
						mediaType = "photo"
						returnToModel = "Image generated successfully. It has been attached to the chat for the user to see."
					}
				}

				toolResponses = append(toolResponses, genai.NewPartFromFunctionResponse(part.FunctionCall.Name, map[string]any{"result": returnToModel}))
			}
		}

		if !hasToolCall {
			break
		}

		// Append tool execution results and loop
		contents = append(contents, &genai.Content{
			Role:  "user",
			Parts: toolResponses,
		})
	}

	resp := &ProcessResponse{
		Reply:       reply,
		RequestID:   requestID,
		MediaBase64: mediaBase64,
		MediaType:   mediaType,
	}

	// 6. Store the bot's reply in the message log
	botReply := &db.Message{
		ChatID:     req.ChatID,
		Text:       &reply,
		IsBotReply: true,
		RequestID:  &requestID,
	}
	if _, err := h.db.InsertMessage(ctx, botReply); err != nil {
		logger.Error("failed to store bot reply", "error", err)
	}

	logger.Info("reply generated", "reply_length", len(reply), "has_media", mediaBase64 != "")
	respondJSON(w, resp)
}

// HandleToolCall processes a function call from Gemini and returns the tool result.
func (h *Handler) HandleToolCall(ctx context.Context, fc *genai.FunctionCall) *tools.ToolResult {
	args, _ := json.Marshal(fc.Args)
	return h.executor.Execute(ctx, fc.Name, args)
}

// respondJSON encodes a response as JSON.
func respondJSON(w http.ResponseWriter, resp *ProcessResponse) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// strPtr returns a pointer to a string, or nil if empty.
func strPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// HealthCheck returns the health status.
func HealthCheck(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"status":"ok"}`)
}
