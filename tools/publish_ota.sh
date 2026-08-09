#!/usr/bin/env bash
# pull型OTA(docs/ota.md)のバイナリを公開する。
#
# 新規ドメイン/CloudFrontは作らず、ダッシュボード配信の既存S3+CloudFrontに
# ota/record/<version>.bin として相乗りする。ファイル名にバージョン(gitの短縮hash)を
# 含むため、公開後に内容が変わることはない（同じ版は同じ内容を指す）。
# CloudFrontは新しいパスを自動で取りに行くので invalidation は不要。
#
# 使い方:
#   tools/publish_ota.sh              # 通常。作業ツリーが汚れていたら拒否する
#   tools/publish_ota.sh --allow-dirty   # 未コミットの変更があっても公開する
#
# 公開しただけでは配らない。実際にデバイスへ配信するには別途:
#   python tools/request_ota.py request <device_id> <表示されたバージョン>
# （配信対象はterraformではなくDynamoDB(生存台帳)に直接書く。配信のたびに
#   terraform applyを要求しない設計にしてある → docs/ota.md）。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIRMWARE_DIR="$ROOT/firmware"
TERRAFORM_DIR="$ROOT/terraform"
OTA_ENV="record"

usage() {
  echo "usage: $0 [--allow-dirty]" >&2
  exit 1
}

ALLOW_DIRTY=0
for arg in "$@"; do
  case "$arg" in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    *) usage ;;
  esac
done

# get_fw_version.py と同じ規則でバージョン文字列を決める（ビルドに実際に
# 埋め込まれるELBZ_FW_VERSIONと一致させる必要がある。ズレるとデバイス側の
# 一致判定が永遠に成立しない）。
FW_VERSION="$(git -C "$ROOT" rev-parse --short HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  if [ "$ALLOW_DIRTY" -ne 1 ]; then
    echo "作業ツリーが汚れている。コミットするか --allow-dirty を付けろ" \
         "（未コミット状態を配布版として公開する事故を防ぐガード）" >&2
    exit 1
  fi
  FW_VERSION="${FW_VERSION}-dirty"
fi

echo "# building env=$OTA_ENV version=$FW_VERSION"
PIO="$ROOT/.venv/bin/pio"
[ -x "$PIO" ] || PIO="$HOME/.platformio/penv/bin/pio"
[ -x "$PIO" ] || PIO=pio
( cd "$FIRMWARE_DIR" && "$PIO" run -e "$OTA_ENV" )

BIN_PATH="$FIRMWARE_DIR/.pio/build/$OTA_ENV/firmware.bin"
[ -f "$BIN_PATH" ] || { echo "ビルド成果物が見つからない: $BIN_PATH" >&2; exit 1; }

SHA256="$(shasum -a 256 "$BIN_PATH" | awk '{print $1}')"
echo "$SHA256" > "$BIN_PATH.sha256"

BUCKET="$(cd "$TERRAFORM_DIR" && terraform output -raw dashboard_bucket)"
KEY_PREFIX="ota/$OTA_ENV/$FW_VERSION"

echo "# uploading to s3://$BUCKET/$KEY_PREFIX.bin (sha256=$SHA256)"
aws s3 cp "$BIN_PATH" "s3://$BUCKET/$KEY_PREFIX.bin"
aws s3 cp "$BIN_PATH.sha256" "s3://$BUCKET/$KEY_PREFIX.sha256"

echo "# done. 次はデバイスへ配信を許可する:"
echo "#   python tools/request_ota.py request <device_id> $FW_VERSION"
