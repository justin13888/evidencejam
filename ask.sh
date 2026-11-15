#!/usr/bin/env bash
# Usage: ./ask.sh [--json] "What effect does prescribed burning have on native plant richness?"
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/scripts/env.sh"
# One live question: an 8 s LLM timeout (the shared endpoint can take >3 s; lexical fallback on failure), the one-call LLM parser fallback for
# how-to and narrative questions, and the batched LLM linker fallback.
export CAMOREASONING_LLM_TIMEOUT="${CAMOREASONING_LLM_TIMEOUT:-8}"
export CAMOREASONING_STRATEGY_PARSER="${CAMOREASONING_STRATEGY_PARSER:-assisted}"
export CAMOREASONING_STRATEGY_LINKER="${CAMOREASONING_STRATEGY_LINKER:-assisted}"
exec "$PY" -m camoreasoning ask "$@"
