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

# --- watchdog（欠測監視。→ docs/cloud.md「watchdog」） ---

variable "slack_webhook_url" {
  type        = string
  sensitive   = true
  default     = ""
  description = "watchdogの通知先Slack Incoming Webhook URL。空ならNullNotifierになり通知しない(batch_uplink.notify.from_env)。"
}

variable "slack_channel" {
  type        = string
  default     = ""
  description = "Slack通知のチャンネル上書き(レガシーIncoming Webhook限定。空ならwebhook既定のまま)。"
}

variable "slack_mention" {
  type        = string
  default     = "<@U0323ESK6>"
  description = "見落とすと実害が大きい通知(欠測・データ遅延・AC入力断)に付けるSlackメンション。空文字で無効化。Namazu(nna774/NamazuHaUrokoGaNai)のwatchdogと同じユーザーIDを既定にしている。"
}

variable "offline_after_seconds" {
  type        = number
  default     = 300
  description = "最終受信からこの秒数を超えたら欠測とみなす。バッチは30秒間隔なので既定300秒＝約10バッチ落ち。"
}

variable "offline_renotify_seconds" {
  type        = number
  default     = 86400
  description = "欠測が続いている間に通知を再送する間隔[秒]。既定1日。"
}

variable "lag_after_seconds" {
  type        = number
  default     = 600
  description = "受信は続いているが測定時刻がこの秒数以上遅れたら「データ遅延」を通知する。既定600秒＝10分。"
}

variable "lag_renotify_seconds" {
  type        = number
  default     = 86400
  description = "データ遅延が続いている間に通知を再送する間隔[秒]。既定1日。"
}

variable "power_fail_renotify_seconds" {
  type        = number
  default     = 86400
  description = "AC入力断(kGfrqFlagPowerFail)が続いている間に通知を再送する間隔[秒]。既定1日。"
}

variable "ota_stuck_after_seconds" {
  type        = number
  default     = 1800
  description = "pull型OTAを許可してからこの秒数を超えて解消しなければ「停滞」とみなす。既定30分。"
}

variable "ota_stuck_renotify_seconds" {
  type        = number
  default     = 86400
  description = "OTA停滞が続いている間に通知を再送する間隔[秒]。既定1日。"
}

variable "watchdog_schedule" {
  type        = string
  default     = "rate(5 minutes)"
  description = "欠測監視watchdogの起動間隔（EventBridge schedule expression）。通知の遅れ ≒ 欠測しきい値 + この間隔。どの頻度でも無料枠に収まるので、遅さの許容度で決める。"
}
