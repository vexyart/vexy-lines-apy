#!/usr/bin/env bash
# install.sh - Install vexy-lines-apy in editable mode
# Vexy Lines is a macOS vector art application.
# Python bindings to the Vexy Lines MCP API and style engine.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Installing vexy-lines-apy in editable mode..."
uv pip install --system -e .

echo "==> Install complete."
