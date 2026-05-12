#!/usr/bin/env bash
# build.sh - Build vexy-lines-apy (Python bindings to Vexy Lines MCP API)
# Vexy Lines is a macOS vector art application.
# Runs ruff lint/format, pytest, then hatch build.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Formatting and linting..."
fd -e py -x uvx autoflake -i {} 2>/dev/null || true
fd -e py -x uvx pyupgrade --py312-plus {} 2>/dev/null || true
fd -e py -x uvx ruff check --output-format=github --fix --unsafe-fixes {} 2>/dev/null || true
fd -e py -x uvx ruff format --respect-gitignore --target-version py312 {} 2>/dev/null || true

echo "==> Running tests..."
uvx hatch test || true

echo "==> Building package..."
uvx hatch clean
uvx hatch build

echo "==> Build complete: dist/"
