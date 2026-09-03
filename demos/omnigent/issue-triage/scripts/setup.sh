#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
GIT_ROOT=$(git -C "$ROOT" rev-parse --show-toplevel)
DEMO_ROOT="$GIT_ROOT/demos/omnigent"
cd "$ROOT"

if [[ ! -f "$DEMO_ROOT/.demo-base" ]]; then
  git -C "$GIT_ROOT" rev-parse HEAD > "$DEMO_ROOT/.demo-base"
  git -C "$GIT_ROOT" branch --show-current > "$DEMO_ROOT/.demo-branch"
fi

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q

echo "READY: seed tests pass"
