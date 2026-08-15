# データ用バケット: series/(累積位相、永久) と bad/(CRC不一致の隔離、永久)。
# Namazu の raw/ に相当する「一時置き場→expire」は無い——GFRQ のバッチは
# series/ に置いた時点で最終形であって、そこから加工して events/ 相当を
# 作る工程がまだ無いため（→ docs/cloud.md）。current version を消す
# lifecycle ルールは無い（今は「存在しない要件への一般化」をしない）。
# noncurrent version の掃除ルールは下にある（バージョニング有効化に伴う後付け）。
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

# series_key()/bad_key()は共に「同一内容の再送は同じキーに上書き」を意図的な
# 設計として持つ(→ lambda/s3keys.py)。batch-uplinkのspool/retryは通常運用で
# 普通に起きるため、バージョニングを有効化しただけだと上書きのたびにnoncurrent
# versionが積み上がり、掃除する仕組みが無いと無期限に残ってcurrent versionの
# 分だけ課金対象が増え続ける。current versionのexpireは掛けない(=保存方針は
# 変えない)まま、noncurrent versionだけを掃除する。日数(30)はNamazuの
# events/保護(PR #85)と揃えた暫定値——実際のretry頻度を見て確度を上げる。
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "cleanup-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
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
