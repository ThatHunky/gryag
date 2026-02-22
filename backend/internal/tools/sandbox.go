package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os/exec"
	"strings"
	"time"

	"github.com/ThatHunky/gryag/backend/internal/config"
)

// SandboxTool handles secure Python code execution in the sandbox container.
type SandboxTool struct {
	config *config.Config
}

// NewSandboxTool creates a new sandbox tool.
func NewSandboxTool(cfg *config.Config) *SandboxTool {
	return &SandboxTool{config: cfg}
}

// RunPythonCode executes Python code in the locked-down sandbox container.
// The sandbox has zero network access, read-only filesystem, and strict resource limits.
func (s *SandboxTool) RunPythonCode(ctx context.Context, args json.RawMessage) (string, error) {
	var params struct {
		Code string `json:"code"`
	}
	if err := json.Unmarshal(args, &params); err != nil {
		return "", fmt.Errorf("parse args: %w", err)
	}

	slog.Info("executing sandbox code", "code_length", len(params.Code))

	timeout := time.Duration(s.config.SandboxTimeoutSeconds) * time.Second
	ctx, cancel := context.WithTimeout(ctx, timeout+5*time.Second)
	defer cancel()

	// Execute via docker run with the pre-built sandbox image.
	// --rm: auto-remove container after execution
	// --network none: zero network access (defense in depth)
	// --read-only: read-only root filesystem
	// --tmpfs /tmp:size=64M: writable temp directory with size limit
	// --memory: RAM limit
	// --cpus: CPU limit
	cmd := exec.CommandContext(ctx, "docker", "run",
		"--rm",
		"--network", "none",
		"--read-only",
		"--tmpfs", "/tmp:size=64M",
		"--memory", fmt.Sprintf("%dm", s.config.SandboxMaxMemoryMB),
		"--cpus", "0.5",
		"-e", fmt.Sprintf("SANDBOX_TIMEOUT_SECONDS=%d", s.config.SandboxTimeoutSeconds),
		"-i",
		"gryag-sandbox",
	)

	cmd.Stdin = strings.NewReader(params.Code)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		// Timed out or failed
		if ctx.Err() != nil {
			return "Code execution timed out.", nil
		}
		errOutput := stderr.String()
		if errOutput == "" {
			errOutput = err.Error()
		}
		return fmt.Sprintf("Execution error:\n%s", errOutput), nil
	}

	output := stdout.String()
	if output == "" {
		output = "(no output)"
	}

	// Cap output length to prevent massive responses
	const maxOutput = 4000
	if len(output) > maxOutput {
		output = output[:maxOutput] + "\n... (output truncated)"
	}

	slog.Info("sandbox execution complete", "output_length", len(output))
	return output, nil
}
