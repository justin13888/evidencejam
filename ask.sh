#!/usr/bin/env bash
# Usage: ./ask.sh "What effect does prescribed burning have on native plant richness?"
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/scripts/env.sh"
exec "$PY" -m camoreasoning ask "$@"
