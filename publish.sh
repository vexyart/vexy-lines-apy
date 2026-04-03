#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m mkdocs build
git add -A
git diff --cached --quiet || git commit -m "chore: Build docs for release"
uvx hatch clean
gitnextver
uvx hatch build
uv publish
