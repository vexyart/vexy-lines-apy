#!/usr/bin/env bash
# this_file: publish.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/release-common.sh"

release_publish_python_package "$SCRIPT_DIR" "$(basename "$SCRIPT_DIR")"
