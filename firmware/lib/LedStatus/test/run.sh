#!/usr/bin/env bash
# freqDeviationToColor() の単体テスト。Arduino に依存しないのでホストの g++ で走る。
# 実機も PlatformIO も要らない（GridFreq/Timebase/Goertzel の test/run.sh と同じ形）。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_ledstatus" \
  "$HERE/test_ledstatus.cpp" "$SRC/LedStatus.cpp"
"$OUT/test_ledstatus"
