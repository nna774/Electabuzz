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
