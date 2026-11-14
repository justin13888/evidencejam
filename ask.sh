#!/usr/bin/env bash
# Usage: ./ask.sh [--json] "What effect does prescribed burning have on native plant richness?"
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/scripts/env.sh"
# One live question: short LLM timeout (lexical fallback on failure) and the batched LLM linker fallback.
export CAMOREASONING_LLM_TIMEOUT="${CAMOREASONING_LLM_TIMEOUT:-3}"
export CAMOREASONING_STRATEGY_LINKER="${CAMOREASONING_STRATEGY_LINKER:-assisted}"
exec "$PY" -m camoreasoning ask "$@"
