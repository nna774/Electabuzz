output "ingest_url" {
  description = "firmware secrets.h の kIngestUrl。"
  value       = aws_lambda_function_url.ingest.function_url
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "api_url" {
  description = "dashboard/config.js の window.ELBZ_API_URL。"
  value       = aws_lambda_function_url.api.function_url
}

output "dashboard_url" {
  description = "ダッシュボードの公開URL(CloudFront既定ドメイン)。"
  value       = "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}

output "dashboard_bucket" {
  value = aws_s3_bucket.dashboard.bucket
}

output "dashboard_distribution_id" {
  description = "デプロイ後の create-invalidation に使う。"
  value       = aws_cloudfront_distribution.dashboard.id
}
