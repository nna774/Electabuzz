# デバイス生存台帳（DynamoDB）。ingestがバッチ受信ごとに1項目upsertし、
# api の /devices が読む。pull型OTAの配信対象(pending_ota_version)もここに持つ
# ——terraform.tfvarsを毎回書き換えてapplyするのは配信のたびには重すぎるため、
# tools/request_ota.py で直接書き込む方式に切り替えた(→ docs/ota.md)。
#
# 書き手・読み手はNamazuと共有の `batch_uplink.devices` モジュール
# （lambda/ingest/handler.pyの`NAMZ_HMAC_SECRET`と同じ理由で、共有ライブラリが
# 期待する環境変数名`NAMZ_DEVICES_TABLE`はそのまま使う。値はElectabuzz独自の
# テーブルを渡す）。
#
# 課金はオンデマンド(PAY_PER_REQUEST)——実機1台、書き込みは数十秒に1回程度で
# 定額キャパシティを確保する意味が無い。
resource "aws_dynamodb_table" "devices" {
  name         = "${local.name}-devices"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"

  attribute {
    name = "device_id"
    type = "N"
  }
}
