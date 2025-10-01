#!/bin/bash
# Download Phi-3-mini model for local fact extraction

set -euo pipefail

MODEL_DIR="models"
MODEL_FILE="phi-3-mini-q4.gguf"
MODEL_URL="https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"

echo "🤖 Downloading Phi-3-mini model for local fact extraction..."
echo ""
echo "Model: Phi-3-mini-4k-instruct (Q4_K_M)"
echo "Size: ~2.2GB"
echo "Location: ${MODEL_DIR}/${MODEL_FILE}"
echo ""

# Create models directory
mkdir -p "$MODEL_DIR"

# Check if model already exists
if [ -f "${MODEL_DIR}/${MODEL_FILE}" ]; then
    echo "✅ Model already exists at ${MODEL_DIR}/${MODEL_FILE}"
    echo "   Delete the file and re-run this script to download again."
    exit 0
fi

# Download with progress
if command -v wget &> /dev/null; then
    echo "📥 Downloading with wget..."
    wget --progress=bar:force \
         --show-progress \
         "$MODEL_URL" \
         -O "${MODEL_DIR}/${MODEL_FILE}"
elif command -v curl &> /dev/null; then
    echo "📥 Downloading with curl..."
    curl -L --progress-bar \
         "$MODEL_URL" \
         -o "${MODEL_DIR}/${MODEL_FILE}"
else
    echo "❌ Error: Neither wget nor curl is available."
    echo "   Please install one of them and try again."
    exit 1
fi

echo ""
echo "✅ Model downloaded successfully!"
echo ""
echo "Next steps:"
echo "1. Add to .env:"
echo "   FACT_EXTRACTION_METHOD=hybrid"
echo "   LOCAL_MODEL_PATH=${MODEL_DIR}/${MODEL_FILE}"
echo "   LOCAL_MODEL_THREADS=4"
echo ""
echo "2. Install llama-cpp-python (if not already installed):"
echo "   pip install -r requirements.txt"
echo ""
echo "3. Start the bot:"
echo "   python -m app.main"
echo ""
echo "   Or with Docker:"
echo "   docker-compose up -d bot"
echo ""
