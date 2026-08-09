# api(/recent)をCloudFront経由にする理由: Lambda Function URLは認証なし公開
# (→ aws_lambda_function_url.api)なので、閲覧人数がそのままS3 List/Get・Lambda
# 呼び出し回数に比例していた。GFRQのバッチは30秒に1本しか増えない
# (→ docs/wire-format.md)ので、それより短い間隔でオリジンを叩いても新しいデータは
# 出てこない。30秒TTLでキャッシュしても鮮度を捨てることにはならず、同時に何人
# 見ていようとオリジンへのアクセス回数をほぼ一定に抑えられる(→ docs/cloud.md)。
#
# ダッシュボード配信(dashboard.tf)と違い、ここはS3オリジンではなくLambda Function
# URLへのカスタムオリジンで、CORSはLambda Function URL側の設定(allow_origins=["*"])
# をそのまま通す——固定値なのでOriginヘッダをキャッシュキーに含める必要が無い。
resource "aws_cloudfront_cache_policy" "api" {
  name        = "${local.name}-api"
  min_ttl     = 0
  default_ttl = 30
  max_ttl     = 30

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "whitelist"
      query_strings {
        # /recent が読むクエリはこの2つだけ(→ docs/cloud.md)。
        items = ["minutes", "start"]
      }
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

resource "aws_cloudfront_distribution" "api" {
  enabled = true

  origin {
    domain_name = trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")
    origin_id   = "api"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.api.id
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
