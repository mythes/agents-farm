#!/usr/bin/env bash
# Rebuild the feature demos: one short recording (docs/demo/NAME.cast, a small text source) and one GIF
# (docs/demo/NAME.gif) per scenario in scripts/record_demo.py.
#
#   scripts/make_demo.sh              rebuild every demo
#   scripts/make_demo.sh resume       rebuild one demo
#
# Needs: agg (asciicast -> GIF) and gifsicle (GIF compression). On macOS: brew install agg gifsicle
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
GIF_BUDGET=358400      # 350 KB per GIF: the repo keeps every version forever
CAST_BUDGET=1945600    # 1.9 MB raw per cast (git stores it compressed, about 3% of this); the repo limit is 2 MB per file

for tool in agg gifsicle; do
  command -v "$tool" >/dev/null || { echo "missing tool: $tool (brew install agg gifsicle)"; exit 1; }
done

if [ $# -gt 0 ]; then names=("$@"); else names=($("$PYTHON" scripts/record_demo.py --list)); fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p docs/demo
failed=0

for name in "${names[@]}"; do
  "$PYTHON" scripts/record_demo.py "$name" "docs/demo/$name.cast" | tail -1
  agg "docs/demo/$name.cast" "$tmp/raw.gif" --font-size 13 --fps-cap 8 --idle-time-limit 2 --last-frame-duration 2 -q
  gifsicle -O3 --lossy=100 --colors 48 "$tmp/raw.gif" -o "docs/demo/$name.gif"
  gif=$(wc -c < "docs/demo/$name.gif" | tr -d ' ')
  cast=$(wc -c < "docs/demo/$name.cast" | tr -d ' ')
  echo "  $name.gif $((gif / 1024)) KB (budget $((GIF_BUDGET / 1024)) KB), $name.cast $((cast / 1024)) KB raw"
  [ "$gif" -le "$GIF_BUDGET" ] || { echo "  over budget: $name.gif (shorten the scenario, or lower --fps-cap or --colors)"; failed=1; }
  [ "$cast" -le "$CAST_BUDGET" ] || { echo "  over budget: $name.cast"; failed=1; }
done
exit $failed
