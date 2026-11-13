#!/usr/bin/env bash
# Judges' path on this machine: fresh clone of HEAD -> ./run.sh -> validate.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone -q "$ROOT" "$TMP/repo"
cd "$TMP/repo"
time ./run.sh questions.yaml answers.json
.venv/bin/python -m camoreasoning validate answers.json --questions questions.yaml
