#!/usr/bin/env bash
# AcInputMonitorの単体テスト。Arduinoに依存しないのでホストのg++で走る。
# 実機もPlatformIOも要らない(GridFreq/Timebase/Goertzel/PpsEdgeのtest/run.shと同じ形)。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_ac_input_monitor" \
  "$HERE/test_ac_input_monitor.cpp" "$SRC/AcInputMonitor.cpp"
"$OUT/test_ac_input_monitor"
