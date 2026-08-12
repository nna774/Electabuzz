output "ingest_url" {
  description = "firmware secrets.h の kIngestUrl。"
  value       = aws_lambda_function_url.ingest.function_url
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "api_url" {
  description = "dashboard/config.js の window.ELBZ_API_URL。カスタムドメインありならそちら、なければCloudFront経由(30秒キャッシュ)。"
  value       = local.custom_domain_enabled ? "https://${var.api_domain}" : "https://${aws_cloudfront_distribution.api.domain_name}"
}

output "api_url_direct" {
  description = "CloudFrontを経由しない生のLambda Function URL。切り分け用。"
  value       = aws_lambda_function_url.api.function_url
}

output "dashboard_url" {
  description = "ダッシュボードの公開URL。カスタムドメインありならそちら、なければCloudFront既定ドメイン。"
  value       = local.custom_domain_enabled ? "https://${var.dashboard_domain}" : "https://${aws_cloudfront_distribution.dashboard.domain_name}"
}

# --- カスタムドメイン用: ../dark-kuins.net-dns の records.yml へ転記する値 ---

output "acm_validation_records" {
  description = "records.yml の acm: セクションへ入れる検証用CNAME(name→value)。まずこれをCloudflareへ。"
  value = local.custom_domain_enabled ? {
    for o in aws_acm_certificate.custom[0].domain_validation_options :
    o.domain_name => {
      name  = o.resource_record_name
      type  = o.resource_record_type
      value = o.resource_record_value
    }
  } : {}
}

output "dashboard_cname_target" {
  description = "records.yml の cname: に入れる electabuzz の向き先(CloudFrontドメイン)。"
  value       = aws_cloudfront_distribution.dashboard.domain_name
}

output "api_cname_target" {
  description = "records.yml の cname: に入れる api.electabuzz の向き先(CloudFrontドメイン)。"
  value       = aws_cloudfront_distribution.api.domain_name
}

output "dashboard_bucket" {
  value = aws_s3_bucket.dashboard.bucket
}

output "dashboard_distribution_id" {
  description = "デプロイ後の create-invalidation に使う。"
  value       = aws_cloudfront_distribution.dashboard.id
}

output "devices_table" {
  description = "デバイス生存台帳(DynamoDB)。tools/request_ota.py --table の既定値と一致させてある。"
  value       = aws_dynamodb_table.devices.name
}
