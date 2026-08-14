#!/usr/bin/env bash
# PpsEdgeDetector（R chのエッジをサブサンプル補間で検出する層）の単体テスト。
# Arduinoに依存しないのでホストのg++で走る。実機もPlatformIOも要らない。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_pps_edge_detector" \
  "$HERE/test_pps_edge_detector.cpp" "$SRC/PpsEdgeDetector.cpp"
"$OUT/test_pps_edge_detector"
