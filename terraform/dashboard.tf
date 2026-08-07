# ダッシュボード配信: 非公開S3 + CloudFront(OAC)。認証なしで誰でも閲覧可。
# Namazuの terraform/dashboard.tf と同じ構成。**カスタムドメインは無し**——
# CloudFrontの既定ドメインで足りるうちは、ACM(us-east-1)や外部DNSリポジトリとの
# 手順の絡み合いを持ち込まない(→ 必要になったらNamazuのcustom_domain.tfを参照)。
resource "aws_s3_bucket" "dashboard" {
  bucket = local.dash_bucket
  # 静的ファイルだけなので destroy 時に中身ごと消せるようにする（作り直しが多い）。
  # データ用バケット(s3.tf)には付けない: 周波数データを誤って一括削除しないため。
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "dashboard" {
  bucket                  = aws_s3_bucket.dashboard.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "dashboard" {
  name                              = "${local.name}-dashboard"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ビューワー(ブラウザ)へは常に Cache-Control: no-cache を付ける。エッジのTTLは
# cache_policy_id(CachingOptimized)側に任せる。S3オブジェクト自体にno-cacheを
# 付けるとエッジ↔S3間の再検証が毎回発生する落とし穴があり、Namazuが実際に踏んで
# いる（terraform/dashboard.tfのコメント参照）ので同じ構成で避ける。
resource "aws_cloudfront_response_headers_policy" "dashboard_no_cache" {
  name = "${local.name}-dashboard-no-cache"
  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = "no-cache"
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "dashboard" {
  enabled             = true
  default_root_object = "index.html"

  origin {
    domain_name              = aws_s3_bucket.dashboard.bucket_regional_domain_name
    origin_id                = "dashboard"
    origin_access_control_id = aws_cloudfront_origin_access_control.dashboard.id
  }

  default_cache_behavior {
    target_origin_id           = "dashboard"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.dashboard_no_cache.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  price_class = "PriceClass_200"
}

data "aws_iam_policy_document" "dashboard_bucket" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.dashboard.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.dashboard.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "dashboard" {
  bucket = aws_s3_bucket.dashboard.id
  policy = data.aws_iam_policy_document.dashboard_bucket.json
}
