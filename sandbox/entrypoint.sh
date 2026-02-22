#!/bin/bash
# Sandbox entrypoint: reads Python code from stdin and executes it.
# Output is captured and returned via stdout.
# This script is executed inside the locked-down sandbox container.

set -euo pipefail

# Read code from stdin
CODE=$(cat)

# Execute with a timeout (configured via SANDBOX_TIMEOUT_SECONDS)
TIMEOUT=${SANDBOX_TIMEOUT_SECONDS:-5}

# Run the code and capture output
timeout "${TIMEOUT}s" python3 -c "$CODE" 2>&1 || echo "SANDBOX_ERROR: execution failed or timed out"
