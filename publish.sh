#!/usr/bin/env bash
# publish.sh - Build, version, and publish vexy-lines-apy
# Vexy Lines is a macOS vector art application.
# Python bindings to the Vexy Lines MCP API and style engine.
# Calls build.sh + install.sh, bumps version with gitnextver, then publishes to PyPI.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Running build..."
"$SCRIPT_DIR/build.sh"

echo "==> Running install..."
"$SCRIPT_DIR/install.sh"

python -m mkdocs build
git add -A
git diff --cached --quiet || git commit -m "chore: Build docs for release"
uvx hatch clean
gitnextver
# If gitnextver skipped tagging (no changes), tag the current commit manually
if ! git describe --exact-match HEAD >/dev/null 2>&1; then
    LAST_TAG=$(git tag --sort=-v:refname | grep "^v[0-9]" | head -1)
    if [ -n "$LAST_TAG" ]; then
        # Bump patch version
        NEXT=$(echo "$LAST_TAG" | awk -F. -v OFS=. "{gsub(/^v/,\"\",\$1); \$NF=\$NF+1; print \"v\"\$0}")
        echo "Creating tag $NEXT on current commit (gitnextver skipped)"
        git tag "$NEXT"
        git push origin "$NEXT"
    fi
fi
uvx hatch build
uv publish
