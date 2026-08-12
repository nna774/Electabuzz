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

variable "dashboard_domain" {
  type        = string
  default     = "electabuzz.dark-kuins.net"
  description = "ダッシュボードのカスタムドメイン。CloudFrontのaliasにする。空ならCloudFront既定ドメイン+既定証明書のまま。"
}

variable "api_domain" {
  type        = string
  default     = "api.electabuzz.dark-kuins.net"
  description = "読み取りAPIのカスタムドメイン。api_cache.tfのCloudFrontにaliasとして足す。空ならCloudFront既定ドメインのまま。"
}
