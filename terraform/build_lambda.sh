#!/usr/bin/env bash
# 各Lambda関数のzipを terraform/builds/<fn>.zip に生成する。
# handler.py + 同階層の依存モジュールを集め、batch_uplink を同梱する。
# terraform apply の前に実行すること。
#
# 今は ingest しか無い（detect/rollup/api は未実装 → docs/roadmap.md）。
# 増えたら Namazu の build_lambda.sh と同じ形で for ループに足す。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
LAMBDA="$REPO/lambda"
BUILD="$HERE/builds"

PY="${PYTHON:-python3}"

# firmware/platformio.ini の lib_deps と揃えること（同じコードの両面なので、
# 片方だけ動かすと食い違う → docs/batch-uplink.md）。
UPLINK_VERSION="v1.6.0"

rm -rf "$BUILD"
mkdir -p "$BUILD"

build_ingest() {
  stage="$BUILD/ingest"
  mkdir -p "$stage"
  cp "$LAMBDA/ingest/handler.py" "$stage/handler.py"
  cp "$LAMBDA/s3keys.py" "$stage/s3keys.py"
  cp "$LAMBDA/wire_gridfreq.py" "$stage/wire_gridfreq.py"
  # 送信基盤の共通部分(auth/devices)。boto3はLambdaランタイムに同梱済みなので
  # ここでは入れない。numpyも不要（wire_gridfreq/s3keysはstdlibのみ）。
  # **タグで pin する。** #master にすると firmware 側の変更が黙って混入する。
  "$PY" -m pip install --quiet --no-deps \
    --target "$stage" "git+https://github.com/nna774/batch-uplink@$UPLINK_VERSION" >/dev/null
  find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
  (cd "$stage" && zip -qr "$BUILD/ingest.zip" .)
  echo "built $BUILD/ingest.zip"
}

build_ingest
