#!/usr/bin/env bash
# Judges' path on this machine: fresh clone of HEAD -> ./run.sh -> validate, with mise off PATH
# and no .env (judges have neither).
set -euo pipefail
PATH="$(printf %s "$PATH" | tr ':' '\n' | grep -v mise | paste -sd: -)"; export PATH
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone -q "$ROOT" "$TMP/repo"
cd "$TMP/repo"
time ./run.sh questions.yaml answers.json
PYTHONPATH=src .venv/bin/python -m camoreasoning validate answers.json --questions questions.yaml
