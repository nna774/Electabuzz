#!/usr/bin/env bash
# GnssNmea(NMEA行組み立て + GGA解析)の単体テスト。
# Arduinoに依存しないのでホストのg++で走る。実機もPlatformIOも要らない。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../src"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT

g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_nmea_line_reader" \
  "$HERE/test_nmea_line_reader.cpp" "$SRC/NmeaLineReader.cpp"
"$OUT/test_nmea_line_reader"

g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" \
  -o "$OUT/test_nmea_gga" \
  "$HERE/test_nmea_gga.cpp" "$SRC/NmeaGga.cpp"
"$OUT/test_nmea_gga"
