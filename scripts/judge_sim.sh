#!/usr/bin/env bash
# ARM64 + Python 3.10 clean checkout (podman + qemu), then a second run with no network and a dead LLM.
# Usage: scripts/judge_sim.sh [image]   Pass BRINE_* through the environment to test the live endpoint.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${1:-docker.io/library/python:3.10-slim}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git clone -q "$ROOT" "$TMP/repo"
run() { podman run --rm --platform linux/arm64 -v "$TMP/repo:/repo:Z" -w /repo "$@"; }
echo "== arm64 clean run (network on: pip install + LLM)"
run -e BRINE_URL -e BRINE_MODEL -e BRINE_API_KEY "$IMAGE" bash -c \
  './run.sh questions.yaml answers.json && .venv/bin/python -m camoreasoning validate answers.json --questions questions.yaml'
echo "== arm64 offline run (no network, unreachable LLM): must still produce valid answers"
run --network none -e BRINE_URL=http://10.255.255.1:9/v1 -e BRINE_MODEL=x -e BRINE_API_KEY=x \
  -e CAMOREASONING_LLM_TIMEOUT=3 "$IMAGE" bash -c \
  './run.sh questions.yaml answers.json && .venv/bin/python -m camoreasoning validate answers.json --questions questions.yaml'
