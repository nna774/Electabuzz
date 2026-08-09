variable "region" {
  type    = string
  default = "ap-northeast-1"
}

variable "project" {
  type    = string
  default = "electabuzz"
}

variable "hmac_secret" {
  type        = string
  sensitive   = true
  description = "全デバイス共通の HMAC 鍵（フォールバック）。device_hmac_secrets に無い device_id はこれで検証される。"
}

variable "device_hmac_secrets" {
  type        = map(string)
  sensitive   = true
  default     = {}
  description = <<-EOT
    device_id => HMAC 鍵。ingest の環境変数 NAMZ_HMAC_SECRET_<id> になる(batch_uplink.auth)。
    キーはファームの kDeviceId を10進文字列にしたもの。
  EOT
}

variable "ota_target_version" {
  type        = string
  default     = ""
  description = <<-EOT
    pull型OTA(docs/ota.md)の配信対象バージョン(gitの短縮hash。tools/publish_ota.shが
    ビルドバイナリと一緒に表示する)。空なら何も配信しない。設定してapplyすると、
    ingestがバッチ送信レスポンスへ X-Elbz-Ota-Version ヘッダとして便乗させ、
    ファームがビルドバージョンと不一致を検出したら自分で取得・書き込みする。
    値を戻す/クリアするのも同じくterraform.tfvars編集+applyで行う
    （DynamoDB等の別経路を持たない、1台構成向けの最小構成）。
  EOT
}
