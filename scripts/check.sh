#!/usr/bin/env bash
# Run all checks. Use it before every commit and in CI-like local runs.
#   tests (security, context, repo hygiene) + static security scan + whitespace check
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"

echo "== tests"
"$PYTHON" -m pytest -q

echo "== bandit"
"$PYTHON" -m bandit -q -r agents_farm

if git rev-parse --git-dir >/dev/null 2>&1; then
  echo "== whitespace"
  git diff --check
  git diff --cached --check
fi

echo "all checks passed"
