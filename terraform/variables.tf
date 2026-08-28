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

# --- detect（周波数逸脱・RoCoF・電圧異常の確定判定。→ docs/cloud.md「detect」） ---

variable "freq_deviation_threshold_hz" {
  type        = number
  default     = 0.15
  description = "|f - f_nominal|がこの値[Hz]を超えた状態がfreq_deviation_hold_records件連続したら周波数逸脱として確定する。旧既定100mHzは実データ(直近8日・22,933バッチ)で102件発火し出すぎていたため、`tools/backtest_detect_thresholds.py`のバックテスト(150mHzなら2件・約98%減)を根拠に150mHzへ校正した(→ docs/log/2026-08-28-detect-freq-threshold-backtest.md)。"
}

variable "freq_deviation_hold_records" {
  type        = number
  default     = 3
  description = "周波数逸脱の連続run検出のhold件数(1レコード=1秒)。単発のノイズで確定させないための最小継続時間。"
}

variable "rocof_threshold_hz_per_s" {
  type        = number
  default     = 0.2
  description = "隣接レコード間の|df/dt|がこの値[Hz/s]を超えたら単発でRoCoF逸脱として確定する(継続判定は無い。それ自体が変化率の測定のため)。docs/cloud.mdの目安(200mHz/s)をそのまま既定にした未校正値。"
}

variable "voltage_deviation_fraction" {
  type        = number
  default     = 0.1
  description = "|v_rms - nominal_v_rms_mv| / nominal_v_rms_mvがこの比率を超えた状態がvoltage_deviation_hold_records件連続したら電圧異常として確定する。docs/cloud.mdの目安(±10%)をそのまま既定にした未校正値。AC入力断(power_fail)中は評価しない。"
}

variable "voltage_deviation_hold_records" {
  type        = number
  default     = 3
  description = "電圧異常の連続run検出のhold件数(1レコード=1秒)。"
}

variable "nominal_v_rms_mv" {
  type        = number
  default     = 10300
  description = "電圧異常判定の基準点[mV]。docs/hardware.mdの実測値(AC100V入力時のトランス二次側実効値)。AFE換算(v_rms_mv)は1点校正のみの暫定値なので、この閾値も暫定——実測で校正すること。"
}
