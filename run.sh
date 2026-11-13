#!/usr/bin/env bash
# Usage: ./run.sh [questions.yaml] [answers.json]   (LLM endpoint from BRINE_URL / BRINE_MODEL / BRINE_API_KEY)
set -euo pipefail
abs() { case "$1" in /*) echo "$1" ;; *) echo "$PWD/$1" ;; esac; }
Q="$(abs "${1:-questions.yaml}")"
OUT="$(abs "${2:-answers.json}")"
. "$(dirname "${BASH_SOURCE[0]}")/scripts/env.sh"
exec "$PY" -m camoreasoning run "$Q" "$OUT"
