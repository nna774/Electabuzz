#!/usr/bin/env bash
# 各Lambda関数のzipを terraform/builds/<fn>.zip に生成する。
# handler.py + 同階層の依存モジュールを集め、batch_uplink を同梱する。
# terraform apply の前に実行すること。
#
# 今は ingest/api/watchdog の3本（detect/rollup は未実装 → docs/roadmap.md）。
# 増えたら Namazu の build_lambda.sh と同じ形で for ループに足す。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
LAMBDA="$REPO/lambda"
BUILD="$HERE/builds"

PY="${PYTHON:-python3}"

# firmware/platformio.ini の lib_deps と揃えること（同じコードの両面なので、
# 片方だけ動かすと食い違う → docs/batch-uplink.md）。
UPLINK_VERSION="v2.12.0"

rm -rf "$BUILD"
mkdir -p "$BUILD"

build_ingest() {
  stage="$BUILD/ingest"
  mkdir -p "$stage"
  cp "$LAMBDA/ingest/handler.py" "$stage/handler.py"
  cp "$LAMBDA/s3keys.py" "$stage/s3keys.py"
  cp "$LAMBDA/wire_gridfreq.py" "$stage/wire_gridfreq.py"
  cp "$LAMBDA/ota_target.py" "$stage/ota_target.py"
  # watchdog向けの状態記録(power_fail_watch/reboot_watch/watchdog_mute)。
  # → docs/cloud.md「watchdog」
  cp -r "$LAMBDA/common" "$stage/common"
  # 送信基盤の共通部分(auth/devices)。boto3はLambdaランタイムに同梱済みなので
  # ここでは入れない。numpyも不要（wire_gridfreq/s3keysはstdlibのみ）。
  # **タグで pin する。** #master にすると firmware 側の変更が黙って混入する。
  "$PY" -m pip install --quiet --no-deps \
    --target "$stage" "git+https://github.com/nna774/batch-uplink@$UPLINK_VERSION" >/dev/null
  find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
  (cd "$stage" && zip -qr "$BUILD/ingest.zip" .)
  echo "built $BUILD/ingest.zip"
}

build_api() {
  stage="$BUILD/api"
  mkdir -p "$stage"
  cp "$LAMBDA/api/handler.py" "$stage/handler.py"
  cp "$LAMBDA/s3keys.py" "$stage/s3keys.py"
  cp "$LAMBDA/wire_gridfreq.py" "$stage/wire_gridfreq.py"
  cp "$LAMBDA/store_gridfreq.py" "$stage/store_gridfreq.py"
  # /devices が devices.list_devices/get_device (batch_uplink) を読むので同梱する。
  # authは使わない(apiは認証しない)が、batch_uplinkはパッケージ単位でしか配れない。
  "$PY" -m pip install --quiet --no-deps \
    --target "$stage" "git+https://github.com/nna774/batch-uplink@$UPLINK_VERSION" >/dev/null
  find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
  (cd "$stage" && zip -qr "$BUILD/api.zip" .)
  echo "built $BUILD/api.zip"
}

build_watchdog() {
  stage="$BUILD/watchdog"
  mkdir -p "$stage"
  cp "$LAMBDA/watchdog/handler.py" "$stage/handler.py"
  # power_fail_watch/reboot_watch/watchdog_mute/ota_watch。S3を触らないので
  # s3keys/wire_gridfreqもnumpyも不要。
  cp -r "$LAMBDA/common" "$stage/common"
  "$PY" -m pip install --quiet --no-deps \
    --target "$stage" "git+https://github.com/nna774/batch-uplink@$UPLINK_VERSION" >/dev/null
  find "$stage" -name '__pycache__' -type d -prune -exec rm -rf {} +
  (cd "$stage" && zip -qr "$BUILD/watchdog.zip" .)
  echo "built $BUILD/watchdog.zip"
}

build_ingest
build_api
build_watchdog
