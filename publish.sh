#!/usr/bin/env bash
cd "$(dirname "$0")"
python -m mkdocs build
uvx hatch clean
gitnextver
uvx hatch build
uv publish