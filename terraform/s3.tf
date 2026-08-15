# データ用バケット: series/(累積位相、永久) と bad/(CRC不一致の隔離、永久)。
# Namazu の raw/ に相当する「一時置き場→expire」は無い——GFRQ のバッチは
# series/ に置いた時点で最終形であって、そこから加工して events/ 相当を
# 作る工程がまだ無いため（→ docs/cloud.md）。ライフサイクルルールは
# 実際に必要になってから足す（今は「存在しない要件への一般化」をしない）。
resource "aws_s3_bucket" "data" {
  bucket = local.data_bucket
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# series/(累積位相の唯一の原本)・bad/(CRC不一致の隔離、捨てると証拠が消える
# →docs/cloud.md)をIAM層とは別の層で誤削除から守る。どちらも再生成不可。
# 実行者本人のAWS認証情報はLambda IAMロールの制限を受けないため、直接AWS
# CLI/コンソールから誤ってDeleteObjectされる事故をここで止める。
# NamazuHaUrokoGaNaiのevents/誤削除防止(PR #85)と同じ構成。
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

data "aws_iam_policy_document" "data_bucket_protect_series" {
  statement {
    sid    = "DenyDeleteSeriesAndBad"
    effect = "Deny"
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.data.arn}/series/*",
      "${aws_s3_bucket.data.arn}/bad/*",
    ]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id
  policy = data.aws_iam_policy_document.data_bucket_protect_series.json
}
