# TE(系統時刻偏差)絶対値表示のセッションアンカー(DynamoDB)。
# → docs/cloud.md「TE絶対値表示のアンカー」、lambda/common/te_anchors.py
#
# events.tf(detectのイベント台帳)と同じ理由でオンデマンド課金・hash_keyのみの
# 単純な形にする。実機1台、runの増える頻度(断線・再起動)も高くないので
# 定額キャパシティを確保する意味が無い。
resource "aws_dynamodb_table" "te_anchors" {
  name         = "${local.name}-te-anchors"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "anchor_id"

  attribute {
    name = "anchor_id"
    type = "S"
  }
}
