#!/usr/bin/env bash
# NtpTimebase（時間基準の回帰）の単体テスト。
# 回帰は Arduino に依存しないのでホストの g++ で走る。実機も PlatformIO も要らない。
#
# **Arduino に依存する部分は MeasuringSntp に閉じ込めてある。** 回帰の側は
# 「単調増加するティック源を NTP 時刻に回帰する」だけなので、ここで数字の正しさを
# 全部詰められる。実機で確かめるのは経路（WiFi と SNTP）の方だけになる。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_ntp_timebase" \
  "$HERE/test_ntp_timebase.cpp" "$SRC/NtpTimebase.cpp"
"$OUT/test_ntp_timebase"

# PpsTimebase（方式Aの回帰）も同じくArduino非依存。→ docs/log/2026-08-12-gnss-pps-wiring-plan.md
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_pps_timebase" \
  "$HERE/test_pps_timebase.cpp" "$SRC/PpsTimebase.cpp"
"$OUT/test_pps_timebase"
