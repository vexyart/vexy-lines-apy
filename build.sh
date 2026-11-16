#!/usr/bin/env bash
# this_file: build.sh
# Build only the adjacent documentation: ./build.sh --docs [renderer options]
if [[ "${1:-}" == --docs ]]; then
  shift
  set -euo pipefail
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
  export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
  exec uvx --python 3.12 --from properdocs==1.6.7 \
    --with mkdocs==1.6.1 \
    --with mkdocs-materialx \
    --with mkdocs-awesome-nav==3.3.0 \
    --with mkdocs-print-site-plugin==2.9 \
    --with pymdown-extensions \
    properdocs build --config-file mkdocs.yml "$@"
fi

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../scripts/release-common.sh"

release_build_python_package "$SCRIPT_DIR" "$(basename "$SCRIPT_DIR")"
release_success "$(basename "$SCRIPT_DIR") build completed."
