# detectが確定した周波数逸脱・RoCoF・電圧異常のイベント台帳（DynamoDB）。
# → docs/cloud.md「detect」、lambda/common/grid_events.py
#
# devices.tf(生存台帳)と同じ理由でオンデマンド課金。実機1台、イベントは
# 常時発生するものではないので定額キャパシティを確保する意味が無い。
resource "aws_dynamodb_table" "events" {
  name         = "${local.name}-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }
}
