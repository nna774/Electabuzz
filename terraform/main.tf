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
    ELBZ_BUCKET             = local.data_bucket
    NAMZ_HMAC_SECRET        = var.hmac_secret
    ELBZ_OTA_TARGET_VERSION = var.ota_target_version
  }, local.device_secret_env)

  # api は読み取り専用・認証なしなので HMAC 鍵は要らない。
  api_env = {
    ELBZ_BUCKET = local.data_bucket
  }
}
