#!/usr/bin/env bash
# this_file: build.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/release-common.sh"

release_build_python_package "$SCRIPT_DIR" "$(basename "$SCRIPT_DIR")"
release_success "$(basename "$SCRIPT_DIR") build completed."
