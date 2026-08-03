#!/usr/bin/env bash
# GFRQ ワイヤ形式の単体テスト。GridFreqWire も Batch も Arduino に依存しないので
# ホストの g++ で走る。実機も PlatformIO も要らない（batch-uplink の test/run.sh と同じ形）。
#
# Batch の実体は共有ライブラリ側にあるので、その在処を解決してから g++ に渡す。
# 探す順序は「pin されている版に近い方から」。
#   1. $BATCH_UPLINK_SRC     — 手で指す（切り出し側を直しながら試すとき）
#   2. .pio/libdeps/*/       — PlatformIO が pin どおりに取ってきた実体
#   3. .cache/               — ここが自分でタグを clone してくる（初回だけ網が要る）
# **兄弟ディレクトリの ../../batch-uplink は見に行かない。** 手元の作業ツリーが
# タグと一致している保証が無く、pin を迂回して「通ったつもり」になるのが一番まずい。
set -euo pipefail

# docs/batch-uplink.md の不変条件どおりタグで pin する。ブランチ追従にするな。
BATCH_UPLINK_TAG=v1.0.0

HERE="$(cd "$(dirname "$0")" && pwd)"
FIRMWARE="$(cd "$HERE/../../.." && pwd)"
REPO="$(cd "$FIRMWARE/.." && pwd)"
GOLDEN="$REPO/testdata/gfrq_v1_golden.hex"

resolve_src() {
  if [ -n "${BATCH_UPLINK_SRC:-}" ]; then
    echo "$BATCH_UPLINK_SRC"; return
  fi
  local libdep
  for libdep in "$FIRMWARE"/.pio/libdeps/*/batch-uplink/src; do
    if [ -f "$libdep/Batch.cpp" ]; then echo "$libdep"; return; fi
  done
  local cache="$FIRMWARE/.cache/batch-uplink-$BATCH_UPLINK_TAG"
  if [ ! -f "$cache/src/Batch.cpp" ]; then
    rm -rf "$cache"
    git clone --quiet --depth 1 --branch "$BATCH_UPLINK_TAG" \
      https://github.com/nna774/batch-uplink.git "$cache" >&2
  fi
  echo "$cache/src"
}

SRC="$(resolve_src)"
echo "batch-uplink: $SRC"

OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -Wall -Wextra -Werror -I "$SRC" -I "$HERE/../src" \
  -DGFRQ_GOLDEN_PATH="\"$GOLDEN\"" \
  -o "$OUT/test_gfrq_wire" \
  "$HERE/test_gfrq_wire.cpp" "$HERE/../src/GridFreqWire.cpp" "$SRC/Batch.cpp"
"$OUT/test_gfrq_wire"
