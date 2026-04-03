#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
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
