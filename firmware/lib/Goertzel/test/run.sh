#!/usr/bin/env bash
# GoertzelEstimator の単体テスト。Arduino に依存しないのでホストの g++ で走る。
# 実機も PlatformIO も要らない（GridFreq/Timebase の test/run.sh と同じ形）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_goertzel" \
  "$HERE/test_goertzel.cpp" "$SRC/Goertzel.cpp"
"$OUT/test_goertzel"
