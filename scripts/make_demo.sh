#!/usr/bin/env bash
# Rebuild the demo: record docs/demo.cast (small text source), then make docs/demo.gif.
# Needs: agg (asciicast -> GIF) and gifsicle (GIF compression). On macOS: brew install agg gifsicle
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
GIF_BUDGET=1048576     # 1 MB: keep the README light
CAST_BUDGET=2097152    # 2 MB raw (git stores it compressed, about 3% of this)

for tool in agg gifsicle; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool (brew install agg gifsicle)"; exit 1; }
done

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

"$PYTHON" scripts/record_demo.py docs/demo.cast
agg docs/demo.cast "$tmp/raw.gif" --font-size 14 --fps-cap 10 --idle-time-limit 2 --last-frame-duration 3 -q
gifsicle -O3 --lossy=80 --colors 64 "$tmp/raw.gif" -o docs/demo.gif

gif=$(wc -c < docs/demo.gif | tr -d ' ')
cast=$(wc -c < docs/demo.cast | tr -d ' ')
echo "docs/demo.gif  $((gif / 1024)) KB (budget $((GIF_BUDGET / 1024)) KB)"
echo "docs/demo.cast $((cast / 1024)) KB raw, $(gzip -9 -c docs/demo.cast | wc -c | awk '{print int($1/1024)}') KB in git"
[ "$gif" -le "$GIF_BUDGET" ] || { echo "GIF is over budget: lower --fps-cap, --colors, or shorten the script"; exit 1; }
[ "$cast" -le "$CAST_BUDGET" ] || { echo "cast is over budget"; exit 1; }
