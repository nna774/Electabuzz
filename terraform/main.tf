data "aws_caller_identity" "current" {}

locals {
  name        = var.project
  data_bucket = "${var.project}-data-${data.aws_caller_identity.current.account_id}"

  # ingest だけが読む環境変数。detect/rollup/api ができたら lambda_env として
  # 共有部分を切り出す（今は ingest 1本なのでその予定を先取りしない）。
  device_secret_env = {
    for id, secret in var.device_hmac_secrets : "NAMZ_HMAC_SECRET_${id}" => secret
  }
  ingest_env = merge({
    ELBZ_BUCKET      = local.data_bucket
    NAMZ_HMAC_SECRET = var.hmac_secret
  }, local.device_secret_env)
}
