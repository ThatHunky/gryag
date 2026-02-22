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

	r.register("weather", &genai.FunctionDeclaration{
		Name:        "weather",
		Description: "Get current weather and forecasts for a location.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"location": {Type: genai.TypeString, Description: "City name or location"},
			},
			Required: []string{"location"},
		},
	})

	r.register("currency", &genai.FunctionDeclaration{
		Name:        "currency",
		Description: "Convert between currencies or get exchange rates.",
		Parameters: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"from":   {Type: genai.TypeString, Description: "Source currency code (e.g. USD)"},
				"to":     {Type: genai.TypeString, Description: "Target currency code (e.g. UAH)"},
				"amount": {Type: genai.TypeNumber, Description: "Amount to convert"},
			},
			Required: []string{"from", "to", "amount"},
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

	// Feature-toggled tools

	if cfg.EnableImageGeneration {
		r.register("generate_image", &genai.FunctionDeclaration{
			Name:        "generate_image",
			Description: "Generate a photorealistic image from a text description using Nano Banana Pro at 2K resolution. Always write prompts in ENGLISH.",
			Parameters: &genai.Schema{
				Type: genai.TypeObject,
				Properties: map[string]*genai.Schema{
					"prompt": {Type: genai.TypeString, Description: "Image generation prompt in ENGLISH"},
				},
				Required: []string{"prompt"},
			},
		})

		r.register("edit_image", &genai.FunctionDeclaration{
			Name:        "edit_image",
			Description: "Edit an existing generated image. Requires the media_id from a previous generation. Always write prompts in ENGLISH.",
			Parameters: &genai.Schema{
				Type: genai.TypeObject,
				Properties: map[string]*genai.Schema{
					"media_id": {Type: genai.TypeString, Description: "The media_id of the image to edit"},
					"prompt":   {Type: genai.TypeString, Description: "Edit instructions in ENGLISH"},
				},
				Required: []string{"media_id", "prompt"},
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

	// Add Google Search Grounding alongside custom tools (confirmed compatible)
	tools := []*genai.Tool{
		{FunctionDeclarations: decls},
	}

	if r.config.EnableWebSearch {
		tools = append(tools, &genai.Tool{
			GoogleSearch: &genai.GoogleSearch{},
		})
	}

	return tools
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
