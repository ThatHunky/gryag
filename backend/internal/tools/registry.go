package tools

import (
	"github.com/ThatHunky/gryag/backend/internal/config"
	"google.golang.org/genai"
)

// Registry holds all available tool declarations, filtered by feature toggles.
type Registry struct {
	config *config.Config
	tools  map[string]*genai.FunctionDeclaration
}

// NewRegistry creates a tool registry with all tools enabled by config.
func NewRegistry(cfg *config.Config) *Registry {
	r := &Registry{
		config: cfg,
		tools:  make(map[string]*genai.FunctionDeclaration),
	}

	// Always-available tools
	r.register("recall_memories", &genai.FunctionDeclaration{
		Name:        "recall_memories",
		Description: "Retrieve stored memories/facts about a specific user. ALWAYS call this before remember_memory to avoid duplicates.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"user_id": {Type: genai.TypeInteger, Description: "Telegram user ID"},
				"chat_id": {Type: genai.TypeInteger, Description: "Telegram chat ID"},
			},
			Required: []string{"user_id", "chat_id"},
		},
	})

	r.register("remember_memory", &genai.FunctionDeclaration{
		Name:        "remember_memory",
		Description: "Store a new fact/memory about a user. MUST call recall_memories first to check for duplicates.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"user_id":     {Type: genai.TypeInteger, Description: "Telegram user ID"},
				"chat_id":     {Type: genai.TypeInteger, Description: "Telegram chat ID"},
				"memory_text": {Type: genai.TypeString, Description: "The fact or memory to store about the user"},
			},
			Required: []string{"user_id", "chat_id", "memory_text"},
		},
	})

	r.register("forget_memory", &genai.FunctionDeclaration{
		Name:        "forget_memory",
		Description: "Delete a specific stored memory by ID. MUST call recall_memories first to get the memory_id.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"memory_id": {Type: genai.TypeInteger, Description: "The ID of the memory to forget"},
			},
			Required: []string{"memory_id"},
		},
	})

	r.register("calculator", &genai.FunctionDeclaration{
		Name:        "calculator",
		Description: "Perform mathematical calculations.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"expression": {Type: genai.TypeString, Description: "Math expression to evaluate"},
			},
			Required: []string{"expression"},
		},
	})

	r.register("search_messages", &genai.FunctionDeclaration{
		Name:        "search_messages",
		Description: "Search through chat message history. Returns matching messages with links and file IDs for media. Use this to recall what someone said or find a specific message/photo/video. You can include the message link in your reply so the user can jump to it.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"chat_id": {Type: genai.TypeInteger, Description: "Telegram chat ID to search in"},
				"query":   {Type: genai.TypeString, Description: "Search query (words to find in messages)"},
				"limit":   {Type: genai.TypeInteger, Description: "Max results to return (default 10, max 50)"},
			},
			Required: []string{"chat_id", "query"},
		},
	})

	if cfg.EnableWebSearch {
		r.register("search_web", &genai.FunctionDeclaration{
			Name:        "search_web",
			Description: "Search the web for current information, news, weather, currency rates, or facts. Use for news, trending topics, weather, currency conversion, or when the user asks for something you need to look up.",
			Parameters: &genai.Schema{
				Type: genai.TypeObject,
				Properties: map[string]*genai.Schema{
					"query": {Type: genai.TypeString, Description: "Search query (e.g. 'latest news Ukraine', 'weather London')"},
				},
				Required: []string{"query"},
			},
		})
	}

	// Feature-toggled tools

	if cfg.EnableImageGeneration {
		r.register("generate_image", &genai.FunctionDeclaration{
			Name:        "generate_image",
			Description: "Generate a photorealistic image from a text description using Gemini 3 Pro Image Preview at 2K resolution. Prompt must be in English only (translate from the user's language). Optional aspect_ratio: use when the user requests specific proportions (e.g. 4:3, 16:9, 4:5); omit for default. Optional as_document: set to true when the user asks to send the image as a file/document (e.g. 'send as file', 'файлом пришли').",
			Parameters: &genai.Schema{
				Type: genai.TypeObject,
				Properties: map[string]*genai.Schema{
					"prompt":        {Type: genai.TypeString, Description: "Image generation prompt in ENGLISH only (translate if needed)."},
					"aspect_ratio":  {Type: genai.TypeString, Description: "Optional. Aspect ratio of the generated image. Supported: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9. Omit for default/auto."},
					"as_document":   {Type: genai.TypeBoolean, Description: "Optional. If true, the image will be sent as a file/document instead of an inline photo. Use when the user asks to receive the image as a file (e.g. 'send as file', 'файлом пришли'). Default false."},
				},
				Required: []string{"prompt"},
			},
		})

		r.register("edit_image", &genai.FunctionDeclaration{
			Name:        "edit_image",
			Description: "Edit an image. Either pass media_id (from a previous generate_image or edit_image tool response) to edit that image, or set use_context_image: true to edit the image attached to the current message. Prompt must be in English only (translate from the user's language). Optional aspect_ratio: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9. Never mention or display media_id to the user—it is for internal use only.",
			Parameters: &genai.Schema{
				Type: genai.TypeObject,
				Properties: map[string]*genai.Schema{
					"media_id":          {Type: genai.TypeString, Description: "Optional. The media_id from a previous generate_image or edit_image tool response (internal; never show this to the user). Omit when use_context_image is true."},
					"use_context_image": {Type: genai.TypeBoolean, Description: "Optional. Set to true when the user attached an image to the current message and asked to edit it. Then omit media_id."},
					"prompt":            {Type: genai.TypeString, Description: "Edit instructions in ENGLISH only."},
					"aspect_ratio":      {Type: genai.TypeString, Description: "Optional. Aspect ratio of the edited image. Supported: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9. Omit for default/auto."},
				},
				Required: []string{"prompt"},
			},
		})
	}

	if cfg.EnableSandbox {
		r.register("run_python_code", &genai.FunctionDeclaration{
			Name:        "run_python_code",
			Description: "Execute Python code in a secure sandbox. Can generate charts, do math, parse data, etc. Code runs in an isolated container with no network access.",
			Parameters: &genai.Schema{
				Type: genai.TypeObject,
				Properties: map[string]*genai.Schema{
					"code": {Type: genai.TypeString, Description: "Python code to execute"},
				},
				Required: []string{"code"},
			},
		})
	}

	return r
}

// register adds a tool to the registry.
func (r *Registry) register(name string, decl *genai.FunctionDeclaration) {
	r.tools[name] = decl
}

// GetTools returns all registered tools as a genai.Tool array for the API call.
func (r *Registry) GetTools() []*genai.Tool {
	if len(r.tools) == 0 {
		return nil
	}

	var decls []*genai.FunctionDeclaration
	for _, d := range r.tools {
		decls = append(decls, d)
	}

	// Only our own function declarations; no proprietary Gemini tools (e.g. Google Search).
	return []*genai.Tool{
		{FunctionDeclarations: decls},
	}
}

// GetToolNames returns the names of all registered tools (for building the tools block text).
func (r *Registry) GetToolNames() []string {
	names := make([]string, 0, len(r.tools))
	for name := range r.tools {
		names = append(names, name)
	}
	return names
}

// GetToolDescription returns a human-readable description of all tools
// for injection into the Dynamic Instructions tools block.
func (r *Registry) GetToolDescription() string {
	desc := ""
	for name, decl := range r.tools {
		desc += "- " + name + ": " + decl.Description + "\n"
	}
	return desc
}

// HasTool checks if a specific tool is registered.
func (r *Registry) HasTool(name string) bool {
	_, ok := r.tools[name]
	return ok
}

// Count returns the number of registered tools.
func (r *Registry) Count() int {
	return len(r.tools)
}
