# Sourced by run.sh/ask.sh: load .env if present, create .venv with pinned deps on first use, export $PY.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then set -a; . "$ROOT/.env"; set +a; fi
PY="$ROOT/.venv/bin/python"
if ! "$PY" -c 'import yaml' 2>/dev/null; then
  if command -v uv >/dev/null 2>&1; then
    uv venv -q --allow-existing "$ROOT/.venv" >&2 && uv pip install -q -p "$PY" -r "$ROOT/requirements.txt" >&2
  else
    python3 -m venv "$ROOT/.venv" >&2 && "$PY" -m pip install -q -r "$ROOT/requirements.txt" >&2
  fi || { echo "setup failed: need python3 >= 3.10 with venv/pip (or uv)" >&2; exit 1; }
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
