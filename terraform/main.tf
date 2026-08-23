data "aws_caller_identity" "current" {}

locals {
  name        = var.project
  data_bucket = "${var.project}-data-${data.aws_caller_identity.current.account_id}"
  dash_bucket = "${var.project}-dashboard-${data.aws_caller_identity.current.account_id}"

  # ingest だけが読む環境変数。detect/rollup ができたら lambda_env として
  # 共有部分を切り出す（今はingest/apiの2本で、ELBZ_BUCKET以外は共有が無いので
  # その予定を先取りしない）。
  device_secret_env = {
    for id, secret in var.device_hmac_secrets : "NAMZ_HMAC_SECRET_${id}" => secret
  }
  ingest_env = merge({
    ELBZ_BUCKET           = local.data_bucket
    NAMZ_HMAC_SECRET      = var.hmac_secret
    NAMZ_DEVICES_TABLE    = aws_dynamodb_table.devices.name
    ELBZ_TE_ANCHORS_TABLE = aws_dynamodb_table.te_anchors.name
  }, local.device_secret_env)

  # api は読み取り専用・認証なしなので HMAC 鍵は要らない。
  # NAMZ_DEVICES_TABLE は /devices の読み取り(devices.list_devices/get_device)に、
  # NAMZ_EVENTS_TABLE は /events の読み取り(grid_events.recent_events)に、
  # ELBZ_TE_ANCHORS_TABLE は /recent のTE計算(te_anchors.anchors_for_session)に使う。
  api_env = {
    ELBZ_BUCKET           = local.data_bucket
    NAMZ_DEVICES_TABLE    = aws_dynamodb_table.devices.name
    NAMZ_EVENTS_TABLE     = aws_dynamodb_table.events.name
    ELBZ_TE_ANCHORS_TABLE = aws_dynamodb_table.te_anchors.name
  }

  # detect は series/ を読み(境界レコードの補完取得)、events/台帳へ書く。
  # NAMZ_DEVICES_TABLEは生存台帳のprev_batch_key読み取り(_prev_boundary_sample_batch、
  # devices.get_device)に使う——ListObjectsV2を置き換えた分(2026-08-23)。
  # Slack設定・ダッシュボードリンク用ドメインはwatchdogと同じ値を渡す(→ docs/cloud.md「detect」)。
  detect_env = {
    ELBZ_BUCKET                   = local.data_bucket
    NAMZ_DEVICES_TABLE            = aws_dynamodb_table.devices.name
    NAMZ_EVENTS_TABLE             = aws_dynamodb_table.events.name
    ELBZ_FREQ_DEV_THRESHOLD_HZ    = tostring(var.freq_deviation_threshold_hz)
    ELBZ_FREQ_DEV_HOLD_RECORDS    = tostring(var.freq_deviation_hold_records)
    ELBZ_ROCOF_THRESHOLD_HZ_PER_S = tostring(var.rocof_threshold_hz_per_s)
    ELBZ_VOLTAGE_DEV_FRACTION     = tostring(var.voltage_deviation_fraction)
    ELBZ_VOLTAGE_DEV_HOLD_RECORDS = tostring(var.voltage_deviation_hold_records)
    ELBZ_NOMINAL_V_RMS_MV         = tostring(var.nominal_v_rms_mv)
    NAMZ_SLACK_WEBHOOK_URL        = var.slack_webhook_url
    NAMZ_SLACK_CHANNEL            = var.slack_channel
    NAMZ_SLACK_MENTION            = var.slack_mention
    NAMZ_DASHBOARD_URL            = local.custom_domain_enabled ? "https://${var.dashboard_domain}" : "https://${aws_cloudfront_distribution.dashboard.domain_name}"
  }

  # watchdog はS3を触らないのでELBZ_BUCKETは要らない。しきい値・Slack設定・
  # ダッシュボードリンク用ドメインだけ渡す(→ docs/cloud.md「watchdog」)。
  watchdog_env = {
    NAMZ_DEVICES_TABLE         = aws_dynamodb_table.devices.name
    NAMZ_OFFLINE_AFTER_S       = tostring(var.offline_after_seconds)
    NAMZ_OFFLINE_RENOTIFY_S    = tostring(var.offline_renotify_seconds)
    NAMZ_LAG_AFTER_S           = tostring(var.lag_after_seconds)
    NAMZ_LAG_RENOTIFY_S        = tostring(var.lag_renotify_seconds)
    NAMZ_POWER_FAIL_RENOTIFY_S = tostring(var.power_fail_renotify_seconds)
    NAMZ_OTA_STUCK_AFTER_S     = tostring(var.ota_stuck_after_seconds)
    NAMZ_OTA_STUCK_RENOTIFY_S  = tostring(var.ota_stuck_renotify_seconds)
    NAMZ_SLACK_WEBHOOK_URL     = var.slack_webhook_url
    NAMZ_SLACK_CHANNEL         = var.slack_channel
    NAMZ_SLACK_MENTION         = var.slack_mention
    NAMZ_DASHBOARD_URL         = local.custom_domain_enabled ? "https://${var.dashboard_domain}" : "https://${aws_cloudfront_distribution.dashboard.domain_name}"
  }
}
